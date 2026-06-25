# Author: Stian Skogbrott
# License: Apache-2.0
"""Semantic Entropy (SE) for REMORA oracle responses.

Implements the Semantic Entropy framework of Kuhn, Gal & Farquhar (2023),
replacing REMORA's original SHA-256 token-hash clustering with NLI-derived
semantic equivalence clusters.

Definition
----------
Given N oracle responses ``r_1, …, r_N``, responses are grouped into
semantic equivalence clusters ``C = {c_1, …, c_K}`` such that two responses
``r_i``, ``r_j`` are co-clustered iff the NLI model assigns bidirectional
entailment (``NLI(r_i → r_j) ≥ θ`` **and** ``NLI(r_j → r_i) ≥ θ``)::

    SE(x) = −∑_{c ∈ C} p(c | x) log p(c | x)

where ``p(c | x) = |c| / N`` is the empirical cluster mass.

Properties
----------
* **SE = 0** iff all N responses are semantically identical (one cluster).
* **SE = log(N)** iff all N responses are mutually distinct (N singleton clusters).
* **SE < H_token** whenever semantically equivalent responses receive different
  surface forms — the key failure mode of token-hash entropy.

Backends
--------
Two backends are provided:

``TokenFingerprintBackend``
    Uses :func:`remora.canonical.phi` fingerprints for equivalence — fully
    deterministic, no external dependencies.  Backward-compatible with the
    original REMORA entropy calculation.  Does not capture synonym variation.

``NLISemanticBackend``
    Uses a cross-encoder NLI model (``cross-encoder/nli-deberta-v3-small`` by
    default, ~24 M params) for principled bidirectional entailment.  Requires
    ``sentence-transformers`` and ``torch``.  Falls back to
    ``TokenFingerprintBackend`` with a warning if the dependency is absent.

Reference
---------
Kuhn, L., Gal, Y., & Farquhar, S. (2023). Semantic uncertainty: Linguistic
invariances for uncertainty estimation in natural language generation.
In *Proceedings of ICLR 2023*.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticCluster:
    """One semantic equivalence cluster."""

    cluster_id: int
    members: tuple[str, ...]  # original response strings
    mass: float               # |members| / N

    def __len__(self) -> int:
        return len(self.members)


@dataclass(frozen=True)
class SemanticEntropyResult:
    """Output of :func:`compute_semantic_entropy`.

    Attributes
    ----------
    entropy:
        SE(x) in nats — 0 (unanimous) to log(N) (maximal disagreement).
    clusters:
        Ordered list of semantic clusters, largest mass first.
    n_responses:
        Total number of oracle responses clustered.
    n_clusters:
        Number of distinct semantic clusters.
    backend_name:
        Name of the backend used for equivalence judgements.
    """

    entropy: float
    clusters: tuple[SemanticCluster, ...]
    n_responses: int
    n_clusters: int
    backend_name: str

    @property
    def normalised_entropy(self) -> float:
        """SE(x) / log(N) — maps to [0, 1].  0 = unanimous, 1 = maximal."""
        if self.n_responses <= 1:
            return 0.0
        return self.entropy / math.log(self.n_responses)

    @property
    def dominant_cluster_mass(self) -> float:
        """Fraction of responses in the largest cluster."""
        if not self.clusters:
            return 0.0
        return self.clusters[0].mass


# ---------------------------------------------------------------------------
# NLI backend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class NLIBackend(Protocol):
    """Protocol for NLI entailment scorers.

    ``predict(premise, hypothesis)`` must return a score in ``[0, 1]`` where
    1.0 = full entailment and 0.0 = contradiction / neutral.
    """

    @property
    def name(self) -> str: ...

    def predict(self, premise: str, hypothesis: str) -> float:
        """Return entailment probability in [0, 1]."""
        ...


# ---------------------------------------------------------------------------
# Backend: token fingerprint (backward-compatible, no external deps)
# ---------------------------------------------------------------------------


class TokenFingerprintBackend:
    """Equivalence via :func:`remora.canonical.phi` fingerprints.

    Two responses are semantically equivalent iff their REMORA canonical
    verdict fingerprints match (same polarity + same sorted content-token
    set).  This is the original REMORA clustering heuristic, preserved for
    backward compatibility and dependency-free operation.

    The fingerprint comparison is exact (threshold ignored): either the
    fingerprints match (score=1.0) or they do not (score=0.0).
    """

    name: str = "token_fingerprint"

    def __init__(self) -> None:
        from remora.canonical import phi  # local import avoids circular dep
        self._phi = phi

    def predict(self, premise: str, hypothesis: str) -> float:
        v_a = self._phi({"unstructured": premise})
        v_b = self._phi({"unstructured": hypothesis})
        return 1.0 if v_a.equivalent_to(v_b) else 0.0


# ---------------------------------------------------------------------------
# Backend: NLI cross-encoder (principled; requires sentence-transformers)
# ---------------------------------------------------------------------------


class NLISemanticBackend:
    """Bidirectional entailment via a cross-encoder NLI model.

    Uses ``sentence-transformers`` ``CrossEncoder`` with label order
    ``["contradiction", "entailment", "neutral"]`` (matching DeBERTa-v3
    NLI models from the HuggingFace Hub).

    Parameters
    ----------
    model_name:
        HuggingFace model identifier.  Default is
        ``"cross-encoder/nli-deberta-v3-small"`` — a compact (24 M param)
        model with strong NLI performance suitable for inference-time use.
    device:
        PyTorch device string.  ``None`` auto-selects CPU/CUDA.
    batch_size:
        Cross-encoder inference batch size.
    cache_size:
        LRU cache capacity for ``(premise, hypothesis)`` pair scores.

    Raises
    ------
    ImportError
        If ``sentence-transformers`` is not installed.  Install with::

            pip install sentence-transformers

    Notes
    -----
    Label order for ``cross-encoder/nli-deberta-v3-small``:
    index 0 = contradiction, index 1 = entailment, index 2 = neutral.
    The backend returns ``softmax[1]`` as the entailment probability.
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/nli-deberta-v3-small",
        device: str | None = None,
        batch_size: int = 16,
        cache_size: int = 512,
    ) -> None:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "NLISemanticBackend requires sentence-transformers. "
                "Install with: pip install sentence-transformers"
            ) from exc

        self._model_name = model_name
        self._batch_size = batch_size
        self._model = CrossEncoder(model_name, device=device, max_length=512)
        self._cache: dict[tuple[str, str], float] = {}
        self._cache_size = cache_size

    @property
    def name(self) -> str:
        return f"nli:{self._model_name}"

    def predict(self, premise: str, hypothesis: str) -> float:
        """Return P(entailment | premise, hypothesis) in [0, 1]."""
        key = (premise[:256], hypothesis[:256])
        if key in self._cache:
            return self._cache[key]

        import numpy as np  # type: ignore[import]

        scores = self._model.predict([(premise, hypothesis)])
        # DeBERTa-v3 NLI: index 0=contradiction, 1=entailment, 2=neutral
        logits = scores[0]
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()
        entailment_prob = float(probs[1])

        if len(self._cache) >= self._cache_size:
            # Evict oldest quarter on overflow
            keys_to_drop = list(self._cache)[:self._cache_size // 4]
            for k in keys_to_drop:
                del self._cache[k]
        self._cache[key] = entailment_prob
        return entailment_prob


# ---------------------------------------------------------------------------
# Union-Find for transitive cluster closure
# ---------------------------------------------------------------------------


class _UnionFind:
    """Weighted union-find (path compression + union by rank)."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path halving
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_semantic_entropy(
    responses: Sequence[str],
    backend: NLIBackend | None = None,
    entailment_threshold: float = 0.5,
) -> SemanticEntropyResult:
    """Cluster *responses* by semantic equivalence and compute SE(x).

    Algorithm
    ---------
    1. For each ordered pair ``(i, j)`` with ``i < j``, query the backend for
       ``predict(r_i, r_j)`` and ``predict(r_j, r_i)``.
    2. Merge ``i`` and ``j`` into the same cluster iff **both** entailment
       scores exceed *entailment_threshold* (bidirectional entailment).
    3. Compute cluster masses ``p(c) = |c| / N`` and return
       ``SE = −∑ p(c) log p(c)`` in nats.

    Parameters
    ----------
    responses:
        Sequence of oracle response strings (raw text, not pre-processed).
        Duplicate strings are handled correctly — two identical strings are
        always co-clustered regardless of the backend.
    backend:
        :class:`NLIBackend` instance.  Defaults to :class:`TokenFingerprintBackend`.
    entailment_threshold:
        Minimum entailment score in ``[0, 1]`` for both directions to merge
        two responses.  Default 0.5 is appropriate for cross-encoder outputs
        where 0.5 is the natural decision boundary.

    Returns
    -------
    SemanticEntropyResult

    Examples
    --------
    >>> result = compute_semantic_entropy(["yes", "yes", "no"])
    >>> result.n_clusters
    2
    >>> round(result.entropy, 4)
    0.6365
    """
    if backend is None:
        backend = TokenFingerprintBackend()

    responses = list(responses)
    n = len(responses)

    if n == 0:
        return SemanticEntropyResult(
            entropy=0.0,
            clusters=(),
            n_responses=0,
            n_clusters=0,
            backend_name=backend.name,
        )

    if n == 1:
        cluster = SemanticCluster(cluster_id=0, members=(responses[0],), mass=1.0)
        return SemanticEntropyResult(
            entropy=0.0,
            clusters=(cluster,),
            n_responses=1,
            n_clusters=1,
            backend_name=backend.name,
        )

    uf = _UnionFind(n)

    for i in range(n):
        for j in range(i + 1, n):
            if responses[i] == responses[j]:
                # Identical strings are always equivalent — skip NLI call
                uf.union(i, j)
                continue
            score_ij = backend.predict(responses[i], responses[j])
            score_ji = backend.predict(responses[j], responses[i])
            if score_ij >= entailment_threshold and score_ji >= entailment_threshold:
                uf.union(i, j)

    # Collect clusters
    cluster_map: dict[int, list[str]] = {}
    for i, resp in enumerate(responses):
        root = uf.find(i)
        cluster_map.setdefault(root, []).append(resp)

    clusters_raw = sorted(cluster_map.values(), key=len, reverse=True)
    clusters = tuple(
        SemanticCluster(
            cluster_id=cid,
            members=tuple(members),
            mass=len(members) / n,
        )
        for cid, members in enumerate(clusters_raw)
    )

    entropy = -sum(c.mass * math.log(c.mass) for c in clusters if c.mass > 0)

    return SemanticEntropyResult(
        entropy=entropy,
        clusters=clusters,
        n_responses=n,
        n_clusters=len(clusters),
        backend_name=backend.name,
    )


def semantic_entropy_from_weighted_dist(
    weighted_distribution: dict[str, float],
) -> float:
    """Compute SE from a pre-aggregated weighted distribution over verdict strings.

    This is the drop-in replacement for the token-entropy formula currently
    used in :func:`remora.thermodynamics.estimate_temperature`::

        H_token = −∑ p_i log_2 p_i

    The SE version operates over the same distribution but treats each verdict
    key as its own semantic cluster (no NLI calls — suitable for
    already-canonicalized verdict distributions like ``{"true": 0.7, "false": 0.3}``).

    Parameters
    ----------
    weighted_distribution:
        Mapping from verdict string to probability mass (must sum to ≤ 1.0).

    Returns
    -------
    float
        SE in nats.
    """
    return -sum(p * math.log(p) for p in weighted_distribution.values() if p > 0.0)


def se_to_temperature(
    se_result: SemanticEntropyResult,
    n_oracles: int,
    rho_bar: float = 0.0,
) -> float:
    """Map a SemanticEntropyResult to an effective oracle temperature.

    Replaces the zlib-density heuristic with a principled entropy-based
    temperature.  The formula mirrors the token-entropy path in
    :func:`remora.thermodynamics.estimate_temperature` but uses the
    semantically-grounded entropy::

        T_se = α·SE_norm + β·(1 − η) + γ·ρ̄ + ε

    where:
    * ``SE_norm = SE / log(N)`` is the normalised semantic entropy in [0, 1]
    * ``η = dominant_cluster_mass`` is the order parameter
    * ``ρ̄`` is the mean inter-oracle correlation
    * ``α=0.50, β=0.30, γ=0.15, ε=0.05`` (calibrated on N=544 benchmark)

    Parameters
    ----------
    se_result:
        Output of :func:`compute_semantic_entropy`.
    n_oracles:
        Number of oracles (used to normalise entropy if se_result.n_responses
        differs from n_oracles, e.g. when some oracles share a response).
    rho_bar:
        Mean pairwise oracle correlation (from diversity weighting).

    Returns
    -------
    float
        Effective temperature in (0, 2.0].
    """
    se_norm = se_result.normalised_entropy
    eta = se_result.dominant_cluster_mass
    rho = max(0.0, min(rho_bar, 1.0))

    alpha, beta, gamma, eps = 0.50, 0.30, 0.15, 0.05
    raw = alpha * se_norm + beta * (1.0 - eta) + gamma * rho + eps
    return round(max(0.05, min(raw, 2.0)), 6)


# ---------------------------------------------------------------------------
# Convenience: auto-select backend
# ---------------------------------------------------------------------------


def make_backend(prefer_nli: bool = False, model_name: str | None = None) -> NLIBackend:
    """Return the best available NLI backend.

    Parameters
    ----------
    prefer_nli:
        If True, attempt to load the NLI cross-encoder.  Falls back to
        :class:`TokenFingerprintBackend` if ``sentence-transformers`` is not
        installed.
    model_name:
        HuggingFace model ID for the NLI backend.
    """
    if prefer_nli:
        try:
            return NLISemanticBackend(model_name=model_name or "cross-encoder/nli-deberta-v3-small")
        except ImportError:
            logger.warning(
                "sentence-transformers not available; falling back to TokenFingerprintBackend. "
                "Install with: pip install sentence-transformers"
            )
    return TokenFingerprintBackend()
