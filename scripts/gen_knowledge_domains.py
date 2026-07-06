#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Generate result artifacts for the five knowledge-domain modules.

    python scripts/gen_knowledge_domains.py
    python scripts/gen_knowledge_domains.py --out-dir results/knowledge_domains

Deterministic and offline (no API keys). Each artifact carries a
`result_provenance_v1` block and a `status` field. Per docs/claim_hygiene.md and
CLAUDE.md, an invariant breach (an orphan claim, a cross-tenant leak, a
non-conforming claim, a quality-floor violation) is NOT silently skipped: the
offending artifact is written with `status: "invalid"` and the script exits
non-zero.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.knowledge_domains import (  # noqa: E402
    cost_routing,
    eval_harness,
    evidence_graph,
    multitenant,
    ontology,
)
from remora.provenance import build_provenance  # noqa: E402


def _artifact(schema: str, result: dict, *, script: str, n_samples: int,
              generated_at: str, ok: bool, notes: str) -> dict:
    return {
        "schema": schema,
        "status": "ok" if ok else "invalid",
        "result": result,
        "provenance": build_provenance(
            script=script, generated_at=generated_at, n_samples=n_samples,
            gate="PASS" if ok else "FAIL", notes=notes,
        ),
    }


def build_all(generated_at: str) -> dict[str, tuple[dict, bool]]:
    script = "scripts/gen_knowledge_domains.py"
    out: dict[str, tuple[dict, bool]] = {}

    ev = eval_harness.evaluate(eval_harness.GOLD, eval_harness.PREDICTIONS)
    out["eval_harness"] = (_artifact(
        "eval_harness_v1", ev, script=script, n_samples=int(ev["n_cases"]),
        generated_at=generated_at, ok=True,
        notes="Grounding P/R/F1 + refusal accuracy over a committed SUT; "
              "grades the scorer, not a live model."), True)

    g = evidence_graph.build_graph(evidence_graph.FIXTURE)
    gm = evidence_graph.metrics(g)
    ok = gm["orphan_claims"] == 0
    out["evidence_graph"] = (_artifact(
        "evidence_graph_v1", gm, script=script, n_samples=gm["n_claims"],
        generated_at=generated_at, ok=ok,
        notes="Register-as-graph integrity over a committed fixture."), ok)

    rep = multitenant.run_isolation_battery()
    md = rep.__dict__
    ok = rep.cross_tenant_leaks == 0 and rep.n_chain_forks == 0
    out["multitenant"] = (_artifact(
        "multitenant_v1", md, script=script, n_samples=rep.n_isolation_checks,
        generated_at=generated_at, ok=ok,
        notes="Tenant-isolation invariant, in-memory model."), ok)

    ot = ontology.validate(ontology.FIXTURE)
    ok = ot["nonconforming"] == 0
    out["ontology"] = (_artifact(
        "ontology_v1", ot, script=script, n_samples=ot["n_claims_checked"],
        generated_at=generated_at, ok=ok,
        notes="Machine-readable claim ontology + register conformance."), ok)

    rt = cost_routing.route(cost_routing.MODELS, cost_routing.WORKLOAD)
    ok = rt["quality_violations"] == 0
    out["cost_routing"] = (_artifact(
        "cost_routing_v1", rt, script=script, n_samples=len(cost_routing.WORKLOAD),
        generated_at=generated_at, ok=ok,
        notes="Cost-aware routing under quality floors; synthetic prices."), ok)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=ROOT / "results" / "knowledge_domains")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    all_ok = True
    for name, (artifact, ok) in build_all(generated_at).items():
        path = args.out_dir / f"{name}.json"
        path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        flag = "ok" if ok else "INVALID"
        print(f"[{flag}] {path.relative_to(ROOT)}  "
              f"{ {k: v for k, v in artifact['result'].items() if not isinstance(v, list)} }")
        all_ok = all_ok and ok
    if not all_ok:
        print("[FAIL] one or more knowledge-domain invariants were violated")
        return 1
    print("[OK] all knowledge-domain artifacts written, status:ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
