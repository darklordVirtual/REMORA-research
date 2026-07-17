#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Golden conformance check: Python decision engine vs OPA/Rego policy.

Evaluates a deterministic golden observation set through both the Python
engine (``RemoraDecisionEngine.decide``) and an OPA policy (via ``opa eval``),
then checks conformance at two levels:

1. **Safety parity (default, always enforced):** on every observation where
   the engine's hard-guard floor fires (``hard_guard_floor(obs)``), the Rego
   ``gate`` must return an action at least as severe as the floor, and on
   pure hard-guard cases it must match the floor exactly. This is the
   property the OPA adapter also enforces at runtime — the check here proves
   the *shipped policy* honors it without relying on the runtime floor.

2. **Strict identity (``--strict``):** every observation must produce the
   identical action in Python and Rego. The bundled example policy is
   illustrative and is NOT expected to pass strict mode — strict mode exists
   for deployments that maintain a full Rego port of the engine and want CI
   to prove equivalence.

Requires the ``opa`` binary on PATH (https://www.openpolicyagent.org).
Exits 1 on conformance failure, 2 if opa is unavailable (explicit, so CI can
distinguish "failed" from "not run").

Usage::

    python scripts/opa_conformance.py                # safety parity
    python scripts/opa_conformance.py --strict       # full identity
    python scripts/opa_conformance.py --policy path/to/your_port.rego --strict
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.policy.decision_engine import (  # noqa: E402
    RemoraDecisionEngine,
    hard_guard_floor,
)
from remora.policy.observation import PolicyObservation  # noqa: E402
from remora.policy.opa_adapter import export_opa_context  # noqa: E402

DEFAULT_POLICY = (
    ROOT / "datasets" / "remora_knowledge_v1" / "policies"
    / "rego_examples" / "remora_action_gate.rego"
)
QUERY = "data.remora.action_gate.gate"

SEVERITY = {
    "accept": 0,
    "verify": 1,
    "abstain": 2,
    "escalate": 3,
}


def golden_observations() -> list[tuple[str, PolicyObservation]]:
    """Deterministic golden set: every hard guard + representative routing."""
    cases: list[tuple[str, PolicyObservation]] = []

    hard_guard_overrides: list[tuple[str, dict]] = [
        ("adversarial", {"adversarial_detected": True}),
        ("schema_invalid", {"schema_valid": False}),
        ("tool_forbidden", {"tool_forbidden": True}),
        ("coercion", {"coercion_detected": True}),
        ("blackmail", {"blackmail_pattern_detected": True}),
        ("counterfactual_failed", {"counterfactual_passed": False}),
        ("contradiction_cycles", {"evidence_contradictions": 2, "contradiction_cycles": 1}),
        ("contradiction_no_cycles", {"evidence_contradictions": 2}),
        ("tainted_argument", {"argument_tainted": True}),
    ]
    for name, overrides in hard_guard_overrides:
        cases.append((
            f"hard_guard:{name}",
            PolicyObservation(question=f"golden {name}", risk_tier="low", **overrides),
        ))

    cases.extend([
        ("clean_low_read_ordered", PolicyObservation(
            question="read service metrics", risk_tier="low", action_type="read",
            phase="ordered", trust_score=0.92,
        )),
        ("dry_run_staging", PolicyObservation(
            question="plan infra change", risk_tier="medium", action_type="dry_run",
            target_environment="staging", phase="ordered", trust_score=0.7,
        )),
        ("medium_ordered", PolicyObservation(
            question="update dashboard config", risk_tier="medium",
            action_type="config_change", phase="ordered", trust_score=0.75,
        )),
        ("high_no_evidence", PolicyObservation(
            question="rotate credentials", risk_tier="high",
            action_type="permission_change", phase="ordered", trust_score=0.8,
        )),
        ("critical_destructive_prod", PolicyObservation(
            question="drop production table", risk_tier="critical",
            action_type="destructive_write", target_environment="prod",
            phase="critical", trust_score=0.5,
        )),
        ("disordered_low_trust", PolicyObservation(
            question="summarize incident", risk_tier="low", action_type="qa",
            phase="disordered", trust_score=0.2,
        )),
    ])
    return cases


def opa_eval(opa: str, policy: Path, obs: PolicyObservation) -> str:
    """Evaluate the Rego gate for one observation; returns lowercase action."""
    input_doc = export_opa_context(obs).to_opa_input()["input"]
    proc = subprocess.run(
        [opa, "eval", "--format", "json", "--data", str(policy),
         "--stdin-input", QUERY],
        input=json.dumps(input_doc),
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"opa eval failed: {proc.stderr.strip()}")
    result = json.loads(proc.stdout)
    expressions = result["result"][0]["expressions"]
    return str(expressions[0]["value"]).lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--strict", action="store_true",
                        help="require identical Python/Rego actions on every case")
    args = parser.parse_args(argv)

    opa = shutil.which("opa")
    if opa is None:
        print("SKIPPED: 'opa' binary not found on PATH — conformance not evaluated.")
        print("Install from https://www.openpolicyagent.org and re-run.")
        return 2

    engine = RemoraDecisionEngine()
    failures: list[str] = []
    print(f"Policy: {args.policy}")
    print(f"Mode:   {'strict identity' if args.strict else 'safety parity'}")
    print("-" * 78)

    for name, obs in golden_observations():
        python_action = engine.decide(obs).action.value
        rego_action = opa_eval(opa, args.policy, obs)
        floor = hard_guard_floor(obs)
        floor_action = floor[0].value if floor else None

        problems: list[str] = []
        if floor_action is not None:
            if name.startswith("hard_guard:") and rego_action != floor_action:
                problems.append(f"hard-guard mismatch (floor={floor_action})")
            elif SEVERITY[rego_action] < SEVERITY[floor_action]:
                problems.append(f"rego below floor (floor={floor_action})")
        if args.strict and rego_action != python_action:
            problems.append("strict mismatch")

        status = "FAIL" if problems else "ok"
        print(f"[{status}] {name:32s} python={python_action:8s} rego={rego_action:8s}"
              + (f"  <- {'; '.join(problems)}" if problems else ""))
        if problems:
            failures.append(name)

    print("-" * 78)
    if failures:
        print(f"CONFORMANCE FAILED: {len(failures)} case(s): {', '.join(failures)}")
        return 1
    print("Conformance passed.")
    if not args.strict:
        print("Note: safety-parity mode. Run with --strict against a full Rego "
              "port to prove complete equivalence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
