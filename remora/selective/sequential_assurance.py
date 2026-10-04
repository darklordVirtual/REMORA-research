# SPDX-License-Identifier: BUSL-1.1
"""Per-decision sequential assurance: assumption-checked, anytime-valid monitoring.

This module is the RF-14 slice-1 implementation. It upgrades the cycle-level
offline bound of ``remora/selective/confidence_sequence.py`` (CLAIM-011) into
a per-decision evidence stream with three statistical instruments and an
explicit premise gate:

1. the shipped Beta-mixture confidence sequence on the adverse-event rate
   (same construction as CLAIM-011, now over resolved decisions);
2. an empirical-Bernstein-style confidence sequence for bounded outcomes in
   [0, 1] (Howard et al. 2021; Waudby-Smith and Ramdas 2024), which adapts to
   the observed variance instead of paying worst-case width;
3. an e-process for the composite null "event rate >= threshold", the
   sequential-test form of the deployment question "is the rate provably
   below the gate threshold yet".

Two design rules come straight out of the CLAIM-011 post-mortem:

* **Per-decision identity.** The CLAIM-011 series counted adapt cycles, and
  AROMER cycles re-score overlapping episode windows, so its independence
  premise is NOT_ESTABLISHED. Here every observation is one resolved
  governance decision with a unique ``decision_id``; a repeated id is a
  premise violation, not a data point.
* **Epoch reset.** A rate estimate is only meaningful for one population.
  When the policy, ToolSpec or model identity changes, the monitor closes the
  current segment and starts a new one. No evidence carries across an epoch
  boundary; borrowing strength across populations would invalidate the bound.

Authority separation
--------------------
Everything here is *statistical population assurance*: statements about the
event rate of a stream of past decisions. It is not, and must never become,
an input to REMORA's per-action authority gate. No ACCEPT/VERIFY/ESCALATE/
BLOCK decision reads this module, and the receipt says so in a machine-readable
field (``authority_separation``). A strong receipt is evidence about a
deployment's history; it authorizes nothing by itself.

Premise gate
------------
The bounds are valid under stated assumptions: decisions are conditionally
independent given the past (or at least form a sequence whose conditional
event probability stays on one side of the tested threshold), labels are
correct, and the population is stable inside an epoch. Independence cannot be
proven from the stream, so the monitor checks what is machine-checkable
(unique decision ids, resolved outcomes only, bounded losses) and reports the
rest as assumptions. The gate reports the QV2-02 vocabulary:
``ESTABLISHED``, ``PARTIALLY_ESTABLISHED``, ``NOT_ESTABLISHED`` or
``CONTRADICTED``. On the latter two the numeric bounds move to
``diagnostics`` with ``valid: false``, so an invalid number cannot be
quoted as a bound.

References
----------
- Ville, J. (1939). Etude critique de la notion de collectif.
- Howard, S. R., Ramdas, A., McAuliffe, J. & Sekhon, J. (2021). Time-uniform,
  nonparametric, nonasymptotic confidence sequences. *Annals of Statistics*
  49(2). arXiv:1810.08240.
- Waudby-Smith, I. & Ramdas, A. (2024). Estimating means of bounded random
  variables by betting. *JRSS-B* 86(1).
- Ramdas, A., Grunwald, P., Vovk, V. & Shafer, G. (2023). Game-theoretic
  statistics and safe anytime-valid inference. *Statistical Science* 38(4).

Scope: library code plus an offline receipt generator. Nothing on the
enforcing path imports this module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from remora.selective.confidence_sequence import bernoulli_upper_confidence_sequence

__all__ = [
    "ESTABLISHED",
    "PARTIALLY_ESTABLISHED",
    "NOT_ESTABLISHED",
    "CONTRADICTED",
    "ASSUMPTION_STATUSES",
    "AUTHORITY_SEPARATION_STATEMENT",
    "STANDING_ASSUMPTIONS",
    "METHOD_BETA_MIXTURE",
    "METHOD_EMPIRICAL_BERNSTEIN",
    "AssuranceEpoch",
    "DecisionOutcome",
    "PremiseCheck",
    "SegmentAssurance",
    "SequentialAssuranceMonitor",
    "SequentialAssuranceReceipt",
    "empirical_bernstein_upper_cs",
    "log_rate_eprocess",
    "outcomes_from_episode_records",
]

#: Assumption-status vocabulary (QV2-02 Phase D). Ordering is worst-first:
#: a receipt aggregates its segments by taking the worst status present.
#:
#: CONTRADICTED: the stream carries positive evidence against a premise
#:     (a repeated decision id proves recounting). Bounds are withheld.
#: NOT_ESTABLISHED: a premise could not be evaluated at all (for example a
#:     segment with zero resolved decisions). Bounds are withheld.
#: PARTIALLY_ESTABLISHED: no contradiction, but at least one check is
#:     degraded (unresolved exclusions, missing cluster identifiers, or
#:     clusters shared by several decisions). Bounds are reported, flagged.
#: ESTABLISHED: every machine-checkable premise passed. Independence itself
#:     remains a stated assumption; ESTABLISHED never certifies it.
CONTRADICTED = "CONTRADICTED"
NOT_ESTABLISHED = "NOT_ESTABLISHED"
PARTIALLY_ESTABLISHED = "PARTIALLY_ESTABLISHED"
ESTABLISHED = "ESTABLISHED"
ASSUMPTION_STATUSES = (CONTRADICTED, NOT_ESTABLISHED, PARTIALLY_ESTABLISHED, ESTABLISHED)

#: Preregistered primary methods. The choice is recorded per stream; the
#: other construction is still computed as a supplementary bound.
METHOD_BETA_MIXTURE = "beta_mixture_cs_v1"
METHOD_EMPIRICAL_BERNSTEIN = "empirical_bernstein_cs_v1"

#: Machine-readable statement of the population/per-action split. The
#: receipt carries this verbatim; tests assert it stays present.
AUTHORITY_SEPARATION_STATEMENT = (
    "Statistical population assurance only. This receipt summarizes a stream "
    "of past decisions and is not consumed by any per-action authority gate; "
    "it changes no ACCEPT/VERIFY/ESCALATE/BLOCK semantics and authorizes no "
    "future action."
)

#: Assumptions no stream inspection can discharge. Stated once here so the
#: receipt, the roadmap and reviewers read the same sentence.
STANDING_ASSUMPTIONS = (
    "Within one epoch, each decision's adverse-event probability is "
    "conditionally stable given the past (independence is the strong form), "
    "ground-truth labels are correct, and the population does not drift "
    "inside an epoch. A policy, ToolSpec or model change starts a new epoch. "
    "These are assumptions, not findings; the receipt's premise checks cover "
    "only the machine-checkable parts (unique decision identity, resolved "
    "outcomes, bounded losses)."
)


# ---------------------------------------------------------------------------
# Epoch identity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssuranceEpoch:
    """Population identity for a monitoring segment.

    Any change in policy, ToolSpec or model identity is a new population and
    closes the current segment. String form, not counters: deployments version
    these surfaces heterogeneously (semver, digest, counter) and the monitor
    only needs equality.
    """

    policy: str
    toolspec: str
    model: str

    def __post_init__(self) -> None:
        for name in ("policy", "toolspec", "model"):
            if not getattr(self, name):
                raise ValueError(f"epoch field {name!r} must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {"policy": self.policy, "toolspec": self.toolspec, "model": self.model}


# ---------------------------------------------------------------------------
# Per-decision observation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionOutcome:
    """One resolved governance decision: the atom of the evidence stream.

    ``decision_id`` must identify the decision exactly once in the whole
    stream. A repeated id means a decision was counted twice (the overlapping
    AROMER cycle-window failure), which contradicts the one-decision-once
    premise and flips the segment to CONTRADICTED.

    ``event`` is the adverse-event indicator under monitoring (for example a
    false accept). ``loss`` is the bounded outcome in [0, 1] fed to the
    empirical-Bernstein sequence; when no finer scale exists it equals the
    event indicator.

    ``cluster_id`` names the independence cluster the decision belongs to
    (one underlying task or template). Several decisions sharing a cluster
    are not independent trials; the premise gate degrades the segment to
    PARTIALLY_ESTABLISHED until the cluster-aware treatment of a later
    slice exists. ``None`` means the stream carries no cluster metadata,
    which is itself degraded: the gate cannot check what it cannot see.

    The remaining optional fields are the provenance spine the QV2-02
    resolved-outcome record requires. The monitor's statistics read only
    ``decision_id``, ``event``, ``loss``, ``epoch``, ``resolved``,
    ``cluster_id`` and ``harmful``; the rest is carried so the receipt can
    bind its numbers to a population, a policy and a resolver.
    """

    decision_id: str
    event: bool
    loss: float
    epoch: AssuranceEpoch
    resolved: bool = True
    verdict: str = ""
    #: Ground-truth polarity of the action, None while unresolved. For
    #: false-accept monitoring over the accept population, event == harmful.
    harmful: bool | None = None
    cluster_id: str | None = None
    tenant: str = ""
    task_id: str = ""
    dispatch_id: str = ""
    executed: bool | None = None
    effect_status: str = ""
    ground_truth_source: str = ""
    ground_truth_provenance: str = ""
    policy_sha: str = ""
    toolspec_digest: str = ""
    toolcall_digest: str = ""
    resolved_at: str = ""
    resolver: str = ""
    resolution_provenance: str = ""

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("decision_id must be non-empty")
        if not 0.0 <= self.loss <= 1.0:
            raise ValueError(f"loss must be in [0, 1], got {self.loss}")


@dataclass(frozen=True)
class PremiseCheck:
    """One machine-checkable premise, or a standing assumption."""

    name: str
    status: str  # "passed" | "degraded" | "contradicted" | "assumed"
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


# ---------------------------------------------------------------------------
# Instrument 2: empirical-Bernstein-style confidence sequence (bounded [0,1])
# ---------------------------------------------------------------------------

def _log_betting_eprocess(
    losses: list[float],
    mu: float,
    alpha: float,
    lambda_cap: float,
    mean_prior: float,
    var_prior: float,
) -> float:
    """log E_n(mu) for the one-sided betting process on the mean of losses.

    Factor i is ``1 + lambda_i (mu - X_i)`` with ``lambda_i`` predictable
    (computed from X_1..X_{i-1} only) and clipped to [0, lambda_cap],
    lambda_cap < 1, so every factor is positive. Under any data distribution
    whose conditional means are all >= mu, each factor has conditional
    expectation <= 1, so E_n(mu) is a nonnegative supermartingale: Ville's
    inequality gives the time-uniform guarantee for ANY predictable lambda
    sequence. The empirical-Bernstein-style tuning below (variance-adaptive,
    in the spirit of Howard et al. 2021 eq. for the sub-gamma case and the
    betting CS of Waudby-Smith and Ramdas 2024) only affects tightness.
    """
    log_e = 0.0
    outcome_sum = 0.0
    var_sum = 0.0
    for i, x in enumerate(losses, start=1):
        trailing_mean = (outcome_sum + mean_prior) / i
        variance_est = (var_sum + var_prior) / i
        lam = math.sqrt(2.0 * math.log(1.0 / alpha) / (variance_est * i))
        lam = min(lam, lambda_cap)
        log_e += math.log1p(lam * (mu - x))
        # Predictable updates: observation i enters only lambda_{i+1}.
        deviation = x - trailing_mean
        var_sum += deviation * deviation
        outcome_sum += x
    return log_e


def empirical_bernstein_upper_cs(
    losses: Iterable[float],
    alpha: float = 0.05,
    lambda_cap: float = 0.5,
    mean_prior: float = 0.0,
    var_prior: float = 1.0,
    tol: float = 1e-10,
) -> float:
    """Upper endpoint of a (1 - alpha) time-uniform CS for E[X], X in [0, 1].

    Valid simultaneously for all n under the sole assumption that each
    conditional mean is the same mu (weakened: the guarantee is
    P(for all n: mu_n-bar-path <= U_n) style for the running mean parameter;
    for iid or stable-conditional-mean streams it is the mean). Variance
    adaptive: low-variance streams get tighter bounds than the worst case.

    Args:
        losses: observed bounded outcomes, each in [0, 1].
        alpha: miscoverage budget over the whole monitoring horizon.
        lambda_cap: clip on the betting fraction; must be in (0, 1). The
            bound stays valid for any cap in (0, 1); smaller caps are more
            conservative under adversarial orderings and wider at k = 0.
        mean_prior / var_prior: pseudo-observation priors stabilizing the
            predictable tuning for small n. They affect tightness, not
            validity.
        tol: bisection tolerance.

    Returns:
        Upper bound in [0, 1]; 1.0 for an empty stream.
    """
    xs = [float(x) for x in losses]
    for x in xs:
        if not 0.0 <= x <= 1.0:
            raise ValueError(f"loss must be in [0, 1], got {x}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if not 0.0 < lambda_cap < 1.0:
        raise ValueError(f"lambda_cap must be in (0, 1), got {lambda_cap}")
    if mean_prior < 0.0 or var_prior <= 0.0:
        raise ValueError("mean_prior must be >= 0 and var_prior > 0")
    if not xs:
        return 1.0

    target = math.log(1.0 / alpha)

    def log_e(mu: float) -> float:
        return _log_betting_eprocess(xs, mu, alpha, lambda_cap, mean_prior, var_prior)

    # Every factor is nondecreasing in mu, so the rejection region is
    # upward-closed. At mu = 0 every factor is 1 - lam*x <= 1, hence
    # E_n(0) <= 1 < 1/alpha: the left bracket never rejects. If even mu = 1
    # does not reach 1/alpha, no candidate is rejected and the bound is 1.
    if log_e(1.0) < target:
        return 1.0
    lo, hi = 0.0, 1.0
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if log_e(mid) < target:
            lo = mid
        else:
            hi = mid
    return hi


# ---------------------------------------------------------------------------
# Instrument 3: e-process for the composite null "event rate >= p0"
# ---------------------------------------------------------------------------

def log_rate_eprocess(
    events: Iterable[bool],
    p0: float,
    worst_factor: float = 0.5,
    prior_strength: float = 10.0,
) -> float:
    """log E_n for testing H0: the conditional event rate is always >= p0.

    Factor i is ``1 + lambda_i (p0 - X_i)`` on the 0/1 event X_i, with
    lambda_i predictable. For any stream whose conditional event rate mu_i
    satisfies mu_i >= p0, E[1 + lambda_i (p0 - X_i) | past] <= 1, so the
    product is an e-process for the composite null and P(exists n: E_n >=
    1/alpha) <= alpha under it. Rejecting H0 at E_n >= 1/alpha is the
    sequential answer to "is the rate provably below p0".

    The predictable tuning aims at the growth-optimal bet against the
    trailing rate: for a Bernoulli alternative q < p0 the log-growth-optimal
    fixed factor is lambda* = (p0 - q) / (p0 (1 - p0)). Two guardrails keep
    the plug-in sane. ``worst_factor`` caps lambda so one event can cost at
    most the fraction (1 - worst_factor) of the capital: the uncapped plug-in
    bets everything on "no events" whenever the trailing rate is 0, and a
    single event then wipes the process out (log factor tends to -inf).
    ``prior_strength`` adds pseudo-observations at the null rate so the
    trailing estimate does not swing the bet at small n. Both affect power
    only: any predictable lambda in [0, 1/(1 - p0)) keeps the e-process
    valid.
    """
    if not 0.0 < p0 < 1.0:
        raise ValueError(f"p0 must be in (0, 1), got {p0}")
    if not 0.0 < worst_factor < 1.0:
        raise ValueError(f"worst_factor must be in (0, 1), got {worst_factor}")
    if prior_strength < 0.0:
        raise ValueError("prior_strength must be >= 0")
    log_e = 0.0
    event_sum = 0.0
    xs = [1.0 if bool(x) else 0.0 for x in events]
    lam_cap = (1.0 - worst_factor) / (1.0 - p0)
    for i, x in enumerate(xs, start=1):
        trailing_rate = (event_sum + prior_strength * p0) / (i - 1 + prior_strength)
        lam = (p0 - trailing_rate) / (p0 * (1.0 - p0))
        lam = min(max(lam, 0.0), lam_cap)
        log_e += math.log1p(lam * (p0 - x))
        event_sum += x
    return log_e


# ---------------------------------------------------------------------------
# Monitor: per-decision stream, epoch segmentation, premise gate
# ---------------------------------------------------------------------------

@dataclass
class _Segment:
    """Mutable accumulator for one epoch; SegmentAssurance is the report."""

    epoch: AssuranceEpoch
    decision_ids: set[str] = field(default_factory=set)
    events: list[bool] = field(default_factory=list)
    losses: list[float] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    n_harmful: int = 0
    cluster_ids: set[str] = field(default_factory=set)
    missing_cluster_ids: int = 0
    resolved_timestamps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SegmentAssurance:
    """Assurance report for one epoch segment."""

    epoch: AssuranceEpoch
    n_resolved: int
    n_harmful: int
    false_accepts: int
    method: str
    point_estimate: float | None
    assumption_status: str
    premise_checks: tuple[PremiseCheck, ...]
    upper_bound: float | None
    supplementary_bounds: dict[str, Any] | None
    e_process: dict[str, Any]
    diagnostics: dict[str, Any] | None
    n_clusters: int
    started_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "epoch_id": _epoch_id(self.epoch),
            "epoch": self.epoch.to_dict(),
            "policy_digest": self.epoch.policy,
            "n_resolved": self.n_resolved,
            "n_harmful": self.n_harmful,
            "false_accepts": self.false_accepts,
            "point_estimate": self.point_estimate,
            "method": self.method,
            "assumption_status": self.assumption_status,
            "premise_checks": [c.to_dict() for c in self.premise_checks],
            "upper_bound": self.upper_bound,
            "supplementary_bounds": self.supplementary_bounds,
            "e_process": self.e_process,
            "n_clusters": self.n_clusters,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }
        if self.diagnostics is not None:
            out["diagnostics"] = self.diagnostics
        return out


def _epoch_id(epoch: AssuranceEpoch) -> str:
    return f"policy={epoch.policy}|toolspec={epoch.toolspec}|model={epoch.model}"


class SequentialAssuranceMonitor:
    """Consumes a per-decision outcome stream and produces receipts.

    The monitor is offline library code: it is fed a recorded stream and
    emits a receipt. It is stateful in the small (per-segment lists) so the
    betting CS can be inverted exactly by bisection.
    """

    def __init__(
        self,
        alpha: float = 0.05,
        threshold: float = 0.05,
        lambda_cap: float = 0.5,
        method: str = METHOD_BETA_MIXTURE,
    ) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        if not 0.0 < threshold < 1.0:
            raise ValueError(f"threshold must be in (0, 1), got {threshold}")
        if method not in (METHOD_BETA_MIXTURE, METHOD_EMPIRICAL_BERNSTEIN):
            raise ValueError(f"unknown preregistered method: {method}")
        self.alpha = alpha
        self.threshold = threshold
        self.lambda_cap = lambda_cap
        #: The preregistered primary method for this stream. Both
        #: constructions are always computed; ``method`` only decides which
        #: one the receipt reports as ``upper_bound``.
        self.method = method
        self._segments: list[_Segment] = []
        self._seen_ids: set[str] = set()
        self._excluded_unresolved = 0

    @property
    def epoch_resets(self) -> int:
        """How many times an epoch change closed a segment."""
        return max(len(self._segments) - 1, 0)

    @property
    def excluded_unresolved(self) -> int:
        return self._excluded_unresolved

    def observe(self, outcome: DecisionOutcome) -> None:
        """Add one resolved decision to the stream.

        Unresolved outcomes are excluded and counted: they carry no label,
        and silently dropping them would hide a selection effect. A repeated
        decision_id is not counted; it is recorded as a premise violation on
        the segment where the repeat appeared, because recounting one
        decision twice is exactly the overlapping-window failure this
        construction exists to remove.
        """
        if not outcome.resolved:
            self._excluded_unresolved += 1
            return
        if not self._segments or self._segments[-1].epoch != outcome.epoch:
            self._segments.append(_Segment(epoch=outcome.epoch))
        seg = self._segments[-1]
        if outcome.decision_id in self._seen_ids:
            seg.duplicate_ids.append(outcome.decision_id)
            return
        self._seen_ids.add(outcome.decision_id)
        seg.decision_ids.add(outcome.decision_id)
        seg.events.append(outcome.event)
        seg.losses.append(outcome.loss)
        if outcome.harmful:
            seg.n_harmful += 1
        if outcome.cluster_id:
            seg.cluster_ids.add(outcome.cluster_id)
        else:
            seg.missing_cluster_ids += 1
        if outcome.resolved_at:
            seg.resolved_timestamps.append(outcome.resolved_at)

    def observe_all(self, outcomes: Iterable[DecisionOutcome]) -> None:
        for outcome in outcomes:
            self.observe(outcome)

    def _segment_report(self, seg: _Segment) -> SegmentAssurance:
        n = len(seg.events)
        k = sum(seg.events)
        if seg.duplicate_ids:
            identity_check = PremiseCheck(
                name="unique_decision_identity",
                status="contradicted",
                detail=(
                    f"{len(seg.duplicate_ids)} repeated decision id(s) withheld: "
                    + ", ".join(sorted(set(seg.duplicate_ids)))
                ),
            )
        else:
            identity_check = PremiseCheck(
                name="unique_decision_identity",
                status="passed",
                detail="every decision id appears once in the whole stream",
            )
        if self._excluded_unresolved:
            resolved_check = PremiseCheck(
                name="resolved_outcomes_only",
                status="degraded",
                detail=(
                    f"{self._excluded_unresolved} unresolved outcome(s) excluded "
                    "stream-wide and counted in the receipt; if resolution "
                    "correlates with the outcome, the stream is selected"
                ),
            )
        else:
            resolved_check = PremiseCheck(
                name="resolved_outcomes_only",
                status="passed",
                detail="no unresolved outcomes were excluded",
            )
        n_clusters = len(seg.cluster_ids)
        if seg.missing_cluster_ids:
            cluster_check = PremiseCheck(
                name="independence_cluster_coverage",
                status="degraded",
                detail=(
                    f"{seg.missing_cluster_ids} of {n} decision(s) carry no "
                    "cluster identifier; they are treated as one cluster per "
                    "decision, which the stream cannot prove"
                ),
            )
        elif n_clusters < n:
            cluster_check = PremiseCheck(
                name="independence_cluster_coverage",
                status="degraded",
                detail=(
                    f"{n} decisions share {n_clusters} cluster(s); decisions "
                    "inside one cluster are not independent trials and the "
                    "cluster-aware treatment is a later slice (RF-14 slice 2)"
                ),
            )
        else:
            cluster_check = PremiseCheck(
                name="independence_cluster_coverage",
                status="passed",
                detail=f"{n} decisions in {n_clusters} singleton clusters",
            )
        checks = [
            identity_check,
            resolved_check,
            cluster_check,
            PremiseCheck(
                name="conditional_independence",
                status="assumed",
                detail=(
                    "not machine-verifiable from the stream; violated by "
                    "construction if decisions are re-scored overlapping "
                    "windows (the CLAIM-011 cycle-level caveat)"
                ),
            ),
            PremiseCheck(
                name="stable_population_within_epoch",
                status="assumed",
                detail="policy, ToolSpec and model identity fixed inside the segment",
            ),
        ]

        log_e = log_rate_eprocess(seg.events, self.threshold)
        e_process = {
            "null": f"event rate >= {self.threshold}",
            "log_e_value": log_e,
            "reject_null_at_alpha": log_e >= math.log(1.0 / self.alpha),
        }
        beta_upper = bernoulli_upper_confidence_sequence(k, n, alpha=self.alpha)
        eb_upper = empirical_bernstein_upper_cs(
            seg.losses, alpha=self.alpha, lambda_cap=self.lambda_cap
        )
        if self.method == METHOD_BETA_MIXTURE:
            primary, supplementary = beta_upper, {METHOD_EMPIRICAL_BERNSTEIN: eb_upper}
        else:
            primary, supplementary = eb_upper, {METHOD_BETA_MIXTURE: beta_upper}

        statuses = {c.status for c in checks}
        if "contradicted" in statuses:
            status = CONTRADICTED
        elif n == 0:
            status = NOT_ESTABLISHED
        elif "degraded" in statuses:
            status = PARTIALLY_ESTABLISHED
        else:
            status = ESTABLISHED
        withhold = status in (CONTRADICTED, NOT_ESTABLISHED)
        return SegmentAssurance(
            epoch=seg.epoch,
            n_resolved=n,
            n_harmful=seg.n_harmful,
            false_accepts=k,
            method=self.method,
            point_estimate=(k / n) if n else None,
            assumption_status=status,
            premise_checks=tuple(checks),
            upper_bound=None if withhold else primary,
            supplementary_bounds=None if withhold else supplementary,
            e_process=e_process,
            diagnostics=(
                {
                    "valid": False,
                    "reason": (
                        f"assumption status {status}: these numbers are "
                        "diagnostics, not quotable bounds"
                    ),
                    "upper_bound": primary,
                    "supplementary_bounds": supplementary,
                }
                if withhold
                else None
            ),
            n_clusters=n_clusters,
            started_at=min(seg.resolved_timestamps) if seg.resolved_timestamps else None,
            updated_at=max(seg.resolved_timestamps) if seg.resolved_timestamps else None,
        )

    def receipt(
        self,
        *,
        monitored_event: str,
        population_definition: str,
        input_description: str,
        generated_by: str,
        cluster_unit: str = (
            "independence cluster: one underlying task or template; "
            "decisions sharing a cluster are not independent trials"
        ),
        source_digest: str | None = None,
        git_commit: str | None = None,
    ) -> "SequentialAssuranceReceipt":
        segments = tuple(self._segment_report(seg) for seg in self._segments)
        status = next(
            (s for s in ASSUMPTION_STATUSES if any(seg.assumption_status == s for seg in segments)),
            NOT_ESTABLISHED,
        )
        return SequentialAssuranceReceipt(
            monitored_event=monitored_event,
            population_definition=population_definition,
            input_description=input_description,
            generated_by=generated_by,
            cluster_unit=cluster_unit,
            alpha=self.alpha,
            threshold=self.threshold,
            assumption_status=status,
            segments=segments,
            excluded_unresolved=self._excluded_unresolved,
            epoch_resets=self.epoch_resets,
            source_digest=source_digest,
            git_commit=git_commit,
        )


@dataclass(frozen=True)
class SequentialAssuranceReceipt:
    """Machine-readable assurance receipt (schema sequential_assurance_receipt_v1).

    One receipt covers one monitored stream; each epoch inside it gets one
    segment with its own counts, bounds and assumption status. The top-level
    ``assumption_status`` is the worst segment status, so a single broken
    epoch degrades the whole receipt.
    """

    monitored_event: str
    population_definition: str
    input_description: str
    generated_by: str
    cluster_unit: str
    alpha: float
    threshold: float
    assumption_status: str
    segments: tuple[SegmentAssurance, ...]
    excluded_unresolved: int
    epoch_resets: int
    source_digest: str | None = None
    git_commit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "sequential_assurance_receipt_v1",
            "generated_by": self.generated_by,
            "monitored_event": self.monitored_event,
            "population_definition": self.population_definition,
            "outcome_unit": "resolved_decision",
            "cluster_unit": self.cluster_unit,
            "input": self.input_description,
            "source_digest": self.source_digest,
            "alpha": self.alpha,
            "threshold": self.threshold,
            "assumption_status": self.assumption_status,
            "authority_separation": AUTHORITY_SEPARATION_STATEMENT,
            "standing_assumptions": STANDING_ASSUMPTIONS,
            "epoch_resets": self.epoch_resets,
            "excluded": {"unresolved": self.excluded_unresolved},
            "segments": [s.to_dict() for s in self.segments],
            "provenance": {"git_commit": self.git_commit},
        }


# ---------------------------------------------------------------------------
# Adapter: AROMER episode records -> per-decision outcome stream
# ---------------------------------------------------------------------------

def outcomes_from_episode_records(
    records: Iterable[dict[str, Any]],
    *,
    epoch: AssuranceEpoch,
    population: str = "accept",
) -> list[DecisionOutcome]:
    """Build the per-decision stream from exported AROMER episode records.

    Each record is one parsed JSONL row from an episode store export (for
    example ``artifacts/aromer_holdout_episodes.jsonl``). The monitored event
    is the false accept: verdict ACCEPT on an action whose ground truth is
    harmful. ``population`` selects the verdict subset under monitoring;
    "accept" is the operationally relevant one, because only accepted actions
    reach the user without a gate stop.

    Records whose ground truth is not a resolved benign/harmful label come
    out with ``resolved=False`` so the monitor excludes and counts them.
    Verdicts and labels are case-normalized; the store has carried both
    casings. Rows without an ``id`` raise: a decision without identity cannot
    enter a stream whose premise is per-decision identity.

    The epoch comes from the caller, not the records: the committed fixtures
    predate epoch tagging, so the deployment (or the demo script) declares
    which population the stream belongs to.
    """
    outcomes: list[DecisionOutcome] = []
    for i, record in enumerate(records):
        decision_id = record.get("id") or record.get("episode_id")
        if not decision_id:
            raise ValueError(f"record {i} has no id; per-decision identity is required")
        verdict = str(record.get("verdict", "")).strip().lower()
        if population != "all" and verdict != population:
            continue
        truth = str(record.get("ground_truth", "")).strip().lower()
        if truth in {"harmful", "benign"}:
            event = truth == "harmful"
            resolved = True
            harmful: bool | None = event
        else:
            event = False
            resolved = False
            harmful = None
        outcomes.append(
            DecisionOutcome(
                decision_id=str(decision_id),
                event=event,
                loss=float(event),
                epoch=epoch,
                resolved=resolved,
                verdict=verdict,
                harmful=harmful,
                cluster_id=record.get("cluster_id"),
                tenant=str(record.get("tenant", "")),
                task_id=str(record.get("task_id", "")),
                dispatch_id=str(record.get("dispatch_id", "")),
                executed=record.get("executed"),
                effect_status=str(record.get("effect_status", "")),
                ground_truth_source=str(record.get("label_source", "")),
                ground_truth_provenance=str(record.get("source", "")),
                policy_sha=str(record.get("policy_sha", "")),
                toolspec_digest=str(record.get("toolspec_digest", "")),
                toolcall_digest=str(record.get("toolcall_digest", "")),
                resolved_at=str(record.get("resolved_at", "")),
                resolver=str(record.get("resolver", "")),
                resolution_provenance=str(record.get("resolution_provenance", "")),
            )
        )
    return outcomes
