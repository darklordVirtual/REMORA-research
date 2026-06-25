#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""REMORA CLI — formal safety verification and governance tooling.

Commands
--------
    remora verify               Run all safety invariant checks
    remora verify --json        JSON output for CI integration
    remora verify --scenario X  Run only scenario X
    remora maturity             Show module stability maturity report

Usage
-----
    python -m remora.cli verify
    python -m remora.cli verify --json
    python -m remora.cli maturity
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _cmd_verify(args: argparse.Namespace) -> int:
    """Delegate to eval_pack harness; fallback to inline invariant checks."""
    harness = _ROOT / "eval_pack" / "run_validation.py"

    if harness.exists():
        import importlib.util
        import sys as _sys
        spec = importlib.util.spec_from_file_location("run_validation", harness)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        _sys.modules["run_validation"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        argv: list[str] = []
        if getattr(args, "scenario", None):
            argv += ["--scenario", args.scenario]
        if getattr(args, "json", False):
            argv += ["--json"]

        rc: int = mod.main(argv)
        if getattr(args, "json", False):
            # main() already printed JSON; annotate with invariants_checked
            pass
        return rc

    # Fallback: inline invariant checks (no eval_pack harness)
    return _inline_verify(args)


def _inline_verify(args: argparse.Namespace) -> int:
    from remora.policy.decision_engine import RemoraDecisionEngine
    from remora.policy.observation import PolicyObservation

    engine = RemoraDecisionEngine()

    def obs(**kwargs):  # type: ignore[no-untyped-def]
        defaults = dict(
            question="cli verify", phase="ordered", trust_score=0.5,
            final_H=0.3, final_D=0.2, risk_tier="medium", domain="generic",
            action_type="read", target_environment="staging",
        )
        defaults.update(kwargs)
        return PolicyObservation(**defaults)

    invariants = [
        ("critical_write_escalates", lambda: (
            engine.decide(obs(action_type="destructive_write", target_environment="prod")).action.value == "ESCALATE"
        )),
        ("human_review_on_escalate", lambda: (
            engine.decide(obs(action_type="destructive_write", target_environment="prod")).human_review_required is True
        )),
        ("decide_never_raises_low", lambda: bool(engine.decide(obs(risk_tier="low")).action.value)),
        ("decide_never_raises_critical", lambda: bool(engine.decide(obs(risk_tier="critical")).action.value)),
    ]

    results = []
    for name, fn in invariants:
        try:
            passed = fn()
        except Exception:
            passed = False
        results.append({"name": name, "passed": passed})

    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)

    if getattr(args, "json", False):
        print(json.dumps({
            "invariants_checked": total,
            "invariants_failed": total - passed_count,
            "passed": passed_count,
            "total": total,
            "results": results,
        }, indent=2))
    else:
        print(f"\nREMORA Safety Invariants — {passed_count}/{total}\n")
        for r in results:
            print(f"  {'checkmark' if r['passed'] else 'x'} {r['name']}")
        print()

    return 0 if passed_count == total else 1


def _cmd_maturity(args: argparse.Namespace) -> int:  # noqa: ARG001
    script = _ROOT / "scripts" / "module_maturity_report.py"
    if not script.exists():
        print("scripts/module_maturity_report.py not found — run Task B1")
        return 1
    import importlib.util
    spec = importlib.util.spec_from_file_location("module_maturity_report", script)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.main()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="remora",
        description="REMORA CLI — formal safety verification and governance tooling",
    )
    sub = parser.add_subparsers(dest="command")

    verify_p = sub.add_parser("verify", help="Run formal safety invariant verification")
    verify_p.add_argument("--json", action="store_true", help="JSON output for CI")
    verify_p.add_argument("--scenario", help="Run only this scenario (by name)")

    sub.add_parser("maturity", help="Show module stability maturity report")

    args = parser.parse_args(argv)

    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "maturity":
        return _cmd_maturity(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
