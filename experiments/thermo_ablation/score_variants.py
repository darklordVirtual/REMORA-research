"""Score thermo-ablation variant outputs against the frozen decision rule.

Reads results/thermo_ablation_results.json. Only permits a "benefit" verdict
when status==ok AND a variant's AURC CI upper bound is below V0's point estimate.
Never emits a claim from a pending/invalid file.
"""
from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).parent / "results" / "thermo_ablation_results.json"


def evaluate(payload: dict) -> dict:
    if payload.get("status") != "ok":
        return {"claims_allowed": False, "verdict": "no-data",
                "reason": f"status={payload.get('status')}"}
    variants = {v["id"]: v for v in payload.get("variants", [])}
    v0 = variants.get("V0")
    if not v0:
        return {"claims_allowed": False, "verdict": "no-baseline"}
    winners = []
    for vid, v in variants.items():
        if vid == "V0":
            continue
        if v.get("aurc_ci95", [1, 1])[1] < v0.get("aurc", 0):
            winners.append(vid)
    return {"claims_allowed": bool(winners), "verdict": "benefit" if winners else "null",
            "winners": winners, "v0_aurc": v0.get("aurc")}


def main() -> int:
    if not RESULTS.exists():
        print("No results file. Run run_ablation.py first. No claim permitted.")
        return 2
    payload = json.loads(RESULTS.read_text())
    verdict = evaluate(payload)
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["claims_allowed"] or verdict["verdict"] in ("null",) else 2


if __name__ == "__main__":
    raise SystemExit(main())
