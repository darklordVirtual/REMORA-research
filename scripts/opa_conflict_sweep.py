#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Sweep a Rego gate policy for rule conflicts and undefined results.

Why this exists
---------------
A Rego *complete rule* may not produce two different values for the same
input. When two ``gate := ...`` rules match with different verdicts, OPA
returns ``eval_conflict_error`` and **no decision at all** — a policy crash,
not a verdict, so there is nothing for the adapter's floor to correct. The
2026-08-04 OT/Rego test set hit exactly that: a HIGH-risk simulate-family
action outside production matched both the dry-run ACCEPT rule and the
high/critical missing-evidence VERIFY rule. The golden conformance set only
carried a MEDIUM dry-run, so CI never reached the conflicting input.

Golden sets pin the cases someone thought of. This sweeps the combinations
of the fields the gate rules actually branch on, so the *class* of defect is
covered rather than one instance of it.

Method
------
The full cartesian product is evaluated in a single ``opa eval`` call: the
cases are emitted as a Rego document and the gate is evaluated per case with
``with input as``. On any policy error the sweep falls back to per-case
evaluation to name the offending inputs precisely.

Exit codes: 0 = no conflicts or undefined results, 1 = at least one, 2 = opa
unavailable.
"""
from __future__ import annotations

import argparse
import itertools
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.policy.observation import PolicyObservation  # noqa: E402
from remora.policy.opa_adapter import export_opa_context  # noqa: E402

DEFAULT_POLICY = (
    ROOT / "datasets" / "remora_knowledge_v1" / "policies"
    / "rego_examples" / "remora_action_gate.rego"
)
GATE = "data.remora.action_gate.gate"

#: Dimensions the shipped gate rules branch on. Values are representatives,
#: not an exhaustive vocabulary: one member per equivalence class the rules
#: can distinguish (e.g. one read-family and one destructive-family verb).
DIMENSIONS: dict[str, tuple] = {
    "risk_tier": ("low", "medium", "high", "critical", None),
    "action_type": ("read", "dry_run", "preview", "write",
                    "config_change", "destructive_write", "permission_change"),
    "target_environment": ("prod", "staging"),
    "phase": ("ordered", "critical", "disordered", None),
    "trust_score": (0.9, 0.3),
    "evidence_action": ("verify", None),
}

#: Hard-block signals. Each is an independent short-circuit in both the engine
#: and the policy, so they are swept one at a time over a small representative
#: base rather than crossed with the full product — crossing them would
#: multiply the case count ten-fold without reaching any new rule interaction.
HARD_SIGNALS: tuple[dict, ...] = (
    {"adversarial_detected": True},
    {"schema_valid": False},
    {"tool_forbidden": True},
    {"argument_tainted": True},
    {"coercion_detected": True},
    {"blackmail_pattern_detected": True},
    {"counterfactual_passed": False},
    {"evidence_contradictions": 2},
    {"evidence_contradictions": 2, "contradiction_cycles": 1},
)

#: Bases the hard signals are applied to: one per risk tier, plus the two
#: action families whose rules can otherwise co-fire (simulate-family and
#: destructive), so a signal that interacts with either is still reached.
HARD_SIGNAL_BASES: tuple[dict, ...] = (
    {"risk_tier": "low", "action_type": "read", "phase": "ordered",
     "trust_score": 0.9, "target_environment": "prod"},
    {"risk_tier": "medium", "action_type": "write", "phase": "ordered",
     "trust_score": 0.7, "target_environment": "prod"},
    {"risk_tier": "high", "action_type": "production_write", "phase": "ordered",
     "trust_score": 0.8, "target_environment": "prod"},
    {"risk_tier": "critical", "action_type": "destructive_write",
     "phase": "critical", "trust_score": 0.5, "target_environment": "prod"},
    {"risk_tier": "high", "action_type": "preview", "phase": "ordered",
     "trust_score": 0.75, "target_environment": "staging"},
    {"risk_tier": None, "action_type": "write", "phase": None,
     "trust_score": 0.6, "target_environment": "prod"},
)


def _label(kwargs: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted(kwargs.items()) if v is not None)


def build_cases() -> list[tuple[str, PolicyObservation]]:
    """Full product over the routing dimensions + hard signals over bases."""
    cases: list[tuple[str, PolicyObservation]] = []
    keys = list(DIMENSIONS)
    for combo in itertools.product(*(DIMENSIONS[k] for k in keys)):
        kwargs = dict(zip(keys, combo))
        # evidence_confidence only matters when evidence is present.
        if kwargs["evidence_action"] is not None:
            kwargs["evidence_confidence"] = 0.7
        cases.append((_label(kwargs), PolicyObservation(question="sweep", **kwargs)))
    for base in HARD_SIGNAL_BASES:
        for signal in HARD_SIGNALS:
            kwargs = {**base, **signal}
            cases.append((_label(kwargs), PolicyObservation(question="sweep", **kwargs)))
    return cases


def _eval_batch(opa: str, policy: Path, docs: list[dict]) -> tuple[list[str] | None, dict | None]:
    """Evaluate every case in one opa call; (values, None) or (None, error)."""
    src = "package sweep\nimport rego.v1\ncases := " + json.dumps(docs) + "\n"
    with tempfile.TemporaryDirectory() as tmp:
        case_file = Path(tmp) / "sweep.rego"
        case_file.write_text(src, encoding="utf-8")
        query = (f"[x | c := data.sweep.cases[_]; x := {GATE} with input as c]")
        proc = subprocess.run(
            [opa, "eval", "--format", "json", "--data", str(policy),
             "--data", str(case_file), query],
            capture_output=True, text=True, timeout=600,
        )
    payload: dict = {}
    if proc.stdout:
        try:
            payload = json.loads(proc.stdout)
        except ValueError:
            payload = {}
    if payload.get("errors"):
        return None, payload["errors"][0]
    if not payload.get("result"):
        return None, {"code": "undefined", "message": "no result document"}
    return list(payload["result"][0]["expressions"][0]["value"]), None


def _eval_single(opa: str, policy: Path, doc: dict) -> str:
    proc = subprocess.run(
        [opa, "eval", "--format", "json", "--data", str(policy),
         "--stdin-input", GATE],
        input=json.dumps(doc), capture_output=True, text=True, timeout=60,
    )
    payload: dict = {}
    if proc.stdout:
        try:
            payload = json.loads(proc.stdout)
        except ValueError:
            payload = {}
    if payload.get("errors"):
        return "!" + str(payload["errors"][0].get("code", "error"))
    if not payload.get("result"):
        return "!undefined"
    return str(payload["result"][0]["expressions"][0]["value"]).lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--show", type=int, default=10,
                        help="how many offending inputs to print")
    args = parser.parse_args(argv)

    opa = shutil.which("opa")
    if opa is None:
        print("SKIPPED: 'opa' binary not found on PATH — sweep not evaluated.")
        return 2

    cases = build_cases()
    docs = [export_opa_context(obs).to_opa_input()["input"] for _, obs in cases]
    print(f"Policy: {args.policy}")
    print(f"Sweep:  {len(cases)} input combinations")

    values, error = _eval_batch(opa, args.policy, docs)
    if error is None:
        assert values is not None
        if len(values) == len(cases):
            print(f"OK: {len(cases)} inputs, every one produced exactly one verdict.")
            return 0
        print(f"Batch returned {len(values)} verdicts for {len(cases)} inputs — "
              "some input produced no value; isolating.")
    else:
        print(f"Policy error in batch [{error.get('code')}]: "
              f"{error.get('message')} — isolating the offending inputs.")

    # Fall back to per-case evaluation to name the offenders precisely.
    offenders: list[tuple[str, str]] = []
    for (label, _obs), doc in zip(cases, docs):
        verdict = _eval_single(opa, args.policy, doc)
        if verdict.startswith("!"):
            offenders.append((label, verdict))

    if not offenders:
        print("No per-case failure reproduced; treating the batch anomaly as "
              "an evaluation artifact, not a policy defect.")
        return 0

    print(f"\nCONFLICT SWEEP FAILED: {len(offenders)} input(s) produced no verdict.")
    for label, verdict in offenders[: args.show]:
        print(f"  [{verdict}] {label}")
    if len(offenders) > args.show:
        print(f"  ... and {len(offenders) - args.show} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
