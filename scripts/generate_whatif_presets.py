#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Generate ``artifacts/demo/whatif_presets_v1.json``: what-if analysis of the
five ``remora try`` presets under the default engine and the execution profile.

The artifact is a committed, reproducible answer to "what would it take for
each preset to be ACCEPTed?", so a reader can see the deployment-fact boundary
without running code. It is regenerated deterministically from the engine and
the lever catalogue; ``--check`` fails when the committed file differs from a
fresh run, which is how a policy change that moves the boundary is noticed.

Usage::

    python scripts/generate_whatif_presets.py            # write
    python scripts/generate_whatif_presets.py --check    # verify committed copy
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "artifacts" / "demo" / "whatif_presets_v1.json"


def build() -> dict[str, Any]:
    from remora.assess import assess_tool_call
    from remora.cli import _TRY_PRESETS
    from remora.policy import RemoraDecisionEngine
    from remora.policy.whatif import LEVERS, what_if

    engines = {
        "default": RemoraDecisionEngine(),
        "execution_profile": RemoraDecisionEngine(execution_profile=True),
    }
    presets = []
    for label, kwargs in _TRY_PRESETS:
        assessment = assess_tool_call(
            kwargs["name"], kwargs["arguments"],
            risk_tier=kwargs.get("risk_tier"), action_type=kwargs.get("action_type"),
            target_environment=kwargs.get("target_environment", "prod"),
            trust_score=kwargs.get("trust_score"), phase=kwargs.get("phase"),
        )
        obs = assessment.decision.raw_observation
        presets.append({
            "label": label,
            "call": {
                "name": kwargs["name"], "arguments": kwargs["arguments"],
                "risk_tier": kwargs.get("risk_tier"),
                "action_type": kwargs.get("action_type"),
                "target_environment": kwargs.get("target_environment", "prod"),
                "trust_score": kwargs.get("trust_score"), "phase": kwargs.get("phase"),
            },
            "verdict": assessment.action,
            "reasons": [r.value for r in assessment.decision.reasons],
            "what_if": {
                name: what_if(obs, engine).to_dict() for name, engine in engines.items()
            },
        })
    return {
        "schema_version": "1",
        "regenerate": "python scripts/generate_whatif_presets.py",
        "check": "python scripts/generate_whatif_presets.py --check",
        "note": (
            "What would have to change for each `remora try` preset to reach "
            "ACCEPT, under the default engine and the execution profile. An "
            "analysis of the policy, not a grant. Levers: remora.policy.whatif.LEVERS."
        ),
        "policy_version": presets[0]["what_if"]["default"] and
            assess_tool_call("probe", {}).decision.policy_version,
        "lever_catalogue": [
            {"name": lv.name, "kind": lv.kind.value,
             "assignments": {k: (list(v) if isinstance(v, tuple) else v)
                             for k, v in lv.assignments},
             "description": lv.description}
            for lv in LEVERS
        ],
        "presets": presets,
    }


def main(argv: list[str]) -> int:
    payload = build()
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    if "--check" in argv:
        if not OUT.exists():
            print(f"[FAIL] {OUT.relative_to(ROOT)} missing; run {payload['regenerate']}")
            return 1
        if OUT.read_text(encoding="utf-8") != text:
            print(f"[FAIL] {OUT.relative_to(ROOT)} is stale; run {payload['regenerate']}")
            return 1
        print(f"[OK]   {OUT.relative_to(ROOT)} is current")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(payload['presets'])} presets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
