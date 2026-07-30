#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Semantic-entropy backend parity smoke (RF-06).

Runs the committed fixture corpus ``data/se_parity/paraphrase_corpus_v1.json``
through both semantic-entropy backends of ``remora/semantic_entropy.py`` and
writes a per-item comparison artifact:

``TokenFingerprintBackend``
    Always available, deterministic, no external deps. This is the backend
    every reported benchmark used so far (``NEGATIVE_RESULTS.md`` section 3,
    Active); ``remora/selective/pvd.py`` likewise defaults to it.

``NLISemanticBackend``
    The NLI cross-encoder route described in the paper, never executed in any
    reported context. Requires the ``nli`` extra (sentence-transformers +
    torch). This script, driven by ``.github/workflows/nli-parity.yml`` on
    ubuntu-latest, is its CI-Linux execution route — local Windows execution
    can be blocked by application control on torch's ``shm.dll``
    (WinError 4551).

When the NLI backend is unavailable the skip is always explicit, never
silent:

* default: write ``{"status": "skipped", "reason": "nli_backend_unavailable"}``
  (fingerprint-side stats still included) and exit 0;
* with ``--require-nli``: write the same skip artifact, print a clear error,
  and exit 2 — for the CI job where NLI execution is the point.

The artifact is deterministic given the pinned model: no timestamps, no
environment-dependent fields beyond the backend name. It is CI-produced and
MUST NOT be committed — the parity result enters the repo only via a later,
provenance-bound round (claim hygiene: no numbers without artifacts).

Usage::

    python scripts/se_backend_parity_smoke.py
    python scripts/se_backend_parity_smoke.py --require-nli \\
        --output results/se_backend_parity_smoke.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from remora.semantic_entropy import (  # noqa: E402
    NLIBackend,
    NLISemanticBackend,
    TokenFingerprintBackend,
    compute_semantic_entropy,
    make_backend,
)

CORPUS_RELPATH = "data/se_parity/paraphrase_corpus_v1.json"
CORPUS_PATH = ROOT / CORPUS_RELPATH
DEFAULT_OUTPUT = ROOT / "results" / "se_backend_parity_smoke.json"
ARTIFACT_SCHEMA = "se_backend_parity_smoke_v1"
CORPUS_SCHEMA = "se_parity_corpus_v1"
ENTAILMENT_THRESHOLD = 0.5


def load_corpus(path: Path) -> dict:
    """Load and structurally validate the parity corpus."""
    corpus = json.loads(path.read_text(encoding="utf-8"))
    if corpus.get("schema") != CORPUS_SCHEMA:
        raise ValueError(f"unexpected corpus schema: {corpus.get('schema')!r}")
    items = corpus.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("corpus has no items")
    if corpus.get("n_items") != len(items):
        raise ValueError(
            f"corpus n_items={corpus.get('n_items')} != len(items)={len(items)}"
        )
    return corpus


def try_load_nli_backend() -> tuple[NLIBackend | None, str | None]:
    """Attempt to load the real NLI backend via make_backend(prefer_nli=True).

    Returns ``(backend, None)`` on success and ``(None, reason)`` on failure.
    Unavailability manifests as an ImportError fallback inside make_backend
    when the ``nli`` extra is missing, but as OSError (WinError 4551) under
    the documented Windows application-control block — hence the deliberately
    broad except.
    """
    try:
        backend = make_backend(prefer_nli=True)
    except Exception as exc:  # e.g. OSError from a blocked torch DLL load
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(backend, NLISemanticBackend):
        return None, "make_backend(prefer_nli=True) fell back to token_fingerprint"
    return backend, None


def backend_stats(responses: Sequence[str], backend: NLIBackend) -> dict:
    """Cluster *responses* under *backend* and return compact SE stats."""
    result = compute_semantic_entropy(
        responses, backend=backend, entailment_threshold=ENTAILMENT_THRESHOLD
    )
    return {
        "n_clusters": result.n_clusters,
        "entropy": round(result.entropy, 6),
        "dominant_cluster_mass": round(result.dominant_cluster_mass, 6),
    }


def run_parity(corpus: dict, nli_backend: NLIBackend | None) -> dict:
    """Compute per-item backend stats; compare when the NLI backend is present."""
    fingerprint_backend = TokenFingerprintBackend()
    items_out: list[dict] = []
    n_cluster_disagreements = 0

    for item in corpus["items"]:
        responses = item["responses"]
        row: dict = {
            "id": item["id"],
            "class": item["class"],
            "n_responses": len(responses),
            "fingerprint": backend_stats(responses, fingerprint_backend),
        }
        if nli_backend is not None:
            row["nli"] = backend_stats(responses, nli_backend)
            row["cluster_count_agreement"] = (
                row["nli"]["n_clusters"] == row["fingerprint"]["n_clusters"]
            )
            if not row["cluster_count_agreement"]:
                n_cluster_disagreements += 1
        items_out.append(row)

    # LF-normalized sha256 of the corpus, matching the manifest hash protocol.
    corpus_bytes = CORPUS_PATH.read_bytes().replace(b"\r\n", b"\n")
    payload: dict = {
        "schema": ARTIFACT_SCHEMA,
        "corpus": CORPUS_RELPATH,
        "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "n_items": len(items_out),
        "entailment_threshold": ENTAILMENT_THRESHOLD,
        "fingerprint_backend": fingerprint_backend.name,
        "items": items_out,
    }
    if nli_backend is not None:
        payload["status"] = "ok"
        payload["summary"] = {
            "n_items": len(items_out),
            "n_cluster_disagreements": n_cluster_disagreements,
            "backend_model_name": nli_backend.name,
        }
    return payload


def write_artifact(payload: dict, output: Path) -> None:
    """Write the artifact with LF newlines (byte-deterministic across runs)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Semantic-entropy backend parity smoke (RF-06)."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="artifact path (default: results/se_backend_parity_smoke.json; never commit it)",
    )
    parser.add_argument(
        "--require-nli",
        action="store_true",
        help="exit non-zero if the NLI backend is unavailable (CI execution route)",
    )
    args = parser.parse_args(argv)

    corpus = load_corpus(CORPUS_PATH)
    nli_backend, unavailable_reason = try_load_nli_backend()

    payload = run_parity(corpus, nli_backend)
    if nli_backend is None:
        payload["status"] = "skipped"
        payload["reason"] = "nli_backend_unavailable"
        payload["detail"] = unavailable_reason
    write_artifact(payload, args.output)

    if nli_backend is None:
        if args.require_nli:
            print(
                f"ERROR: --require-nli set but the NLI backend is unavailable "
                f"({unavailable_reason}); skip artifact written to {args.output}",
                file=sys.stderr,
            )
            return 2
        print(
            f"SKIPPED (explicit): NLI backend unavailable ({unavailable_reason}); "
            f"fingerprint-only artifact written to {args.output}"
        )
        return 0

    summary = payload["summary"]
    print(
        f"OK: {summary['n_items']} items, "
        f"{summary['n_cluster_disagreements']} cluster-count disagreements, "
        f"model={summary['backend_model_name']}; artifact written to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
