#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Run the bundled demo scenarios through REMORA and print the verdicts.

The 60-second developer demo (docs/demo-strategy.md, concept #2): feed three
proposed agent actions to the policy engine and show that each is gated to a
different governed outcome, before anything executes.

    python examples/demo_scenarios/run_demo_scenarios.py

No API keys required — pure PolicyObservation -> RemoraDecisionEngine.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from remora.policy import PolicyObservation, RemoraDecisionEngine  # noqa: E402

SCENARIO_DIR = Path(__file__).parent
ORDER = [
    "safe_read_accept.json",
    "tainted_write_verify.json",
    "wire_transfer_escalate.json",
]
_ICON = {"accept": "ACCEPT  ", "verify": "VERIFY  ", "abstain": "ABSTAIN ", "escalate": "ESCALATE"}


def main() -> int:
    engine = RemoraDecisionEngine()
    print("\nREMORA — pre-execution governance demo")
    print("=" * 60)
    ok = True
    for fname in ORDER:
        data = json.loads((SCENARIO_DIR / fname).read_text(encoding="utf-8"))
        obs = PolicyObservation(**data["observation"])
        report = engine.decide(obs)
        verdict = report.action.value.lower()
        expected = data.get("expected_verdict", "")
        match = "ok" if verdict == expected else "DIFFERS"
        if verdict != expected:
            ok = False
        print(f"\n  {data['name']}")
        print(f"    action     : {data['observation']['question'][:64]}")
        verdict_label = _ICON.get(verdict, verdict.upper())
        print(f"    VERDICT    : {verdict_label}   (expected {expected}: {match})")
        reasons = [r.value if hasattr(r, "value") else str(r) for r in report.reasons]
        if reasons:
            print(f"    reason     : {reasons[0]}")
    print("\n" + "=" * 60)
    print("Nothing above executed. Each action was gated before any tool ran.")
    print("Full story + paper: https://github.com/darklordVirtual/REMORA\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
