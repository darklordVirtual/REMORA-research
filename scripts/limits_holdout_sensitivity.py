#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A post-hoc sensitivity analysis of the limits holdout: refused writes made by hand.

    python scripts/limits_holdout_sensitivity.py SHIFTS.json [...] --out RESULT.json

Not part of the preregistered plan (docs/assurance/ot_limits_holdout_plan_v1.md).
The review of #1185 pointed out that the plan's no-retry rule, a refused write
leaves the plant where it was, does not bound P2 in a known direction. This
replays the same shifts under the opposite assumption: the operator makes a
refused move by hand, outside REMORA, so the plant moves and the ledger charges
nothing, as it charges nothing for any change made outside REMORA. The observed
meters then see that change on the next governed write.

It reuses the frozen harness (scripts/run_limits_holdout.py) for the policy,
the plant, the shift format and the measures; only the handling of a refusal
differs. P1 is the same under both readings, because the first refusal in a
shift does not depend on anything refused earlier.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("run_limits_holdout",
                                               ROOT / "scripts" / "run_limits_holdout.py")
H = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(H)


def replay_shift_by_hand(shift: dict[str, Any], policy, registry, pristine: dict[str, Any],
                         workdir: Path) -> list[dict[str, Any]]:
    from remora.enforcement.cumulative_limits import LimitGuard, LimitLedger

    registry.PLANT.clear()
    registry.PLANT.update(copy.deepcopy(pristine))
    tools = {name: getattr(registry, name) for name in H.TOOLS}
    guard = LimitGuard(policy, LimitLedger(workdir / f"{shift['shift_id']}.db"),
                       is_write=lambda tool: tool != "read_sensor",
                       observer=registry.observe_limit_value)
    rows = []
    for i, w in enumerate(shift.get("writes") or []):
        op = f"{shift['shift_id']}:{i:03d}"
        now = H.SHIFT_START + 60.0 * w["t_min"]
        row = {"shift_id": shift["shift_id"], "index": i, "t_min": w["t_min"],
               "tool": w["tool"], "args": w["args"]}
        refusal = guard.reserve(tenant=H.TENANT, principal=H.PRINCIPAL, tool_name=w["tool"],
                                arguments=w["args"], operation_id=op,
                                request_hash=H._request_hash(w["tool"], w["args"]), now=now)
        stage = "reserve"
        if refusal is None:
            refusal, stage = guard.fence(op), "fence"
        if refusal is None:
            refusal, stage = guard.begin(op), "begin"
        if refusal is not None:
            if stage != "reserve":
                guard.release(op)
            tools[w["tool"]](w["args"])  # made by hand, outside REMORA: nothing is charged
            rows.append({**row, "outcome": "refused", "reason": str(refusal), "stage": stage,
                         "limits": H._limits_named(guard, policy, w), "made_by_hand": True})
            continue
        result = tools[w["tool"]](w["args"])
        guard.settle(op, True, result=result, now=now)
        rows.append({**row, "outcome": "ran"})
    return rows


def run(paths: list[Path]) -> dict[str, Any]:
    policy, digest, kid = H.load_policy()
    registry = H._registry()
    pristine = copy.deepcopy(registry.PLANT)
    shifts, inputs = [], []
    for path in paths:
        data = path.read_bytes()
        inputs.append({"path": path.name, "sha256": hashlib.sha256(data).hexdigest()})
        shifts.extend(H.validate(json.loads(data)))
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        for shift in shifts:
            rows.extend(replay_shift_by_hand(shift, policy, registry, pristine, Path(tmp)))
    return {"analysis": "post hoc: a refused write is made by hand outside REMORA "
                        "(not preregistered; see the script's docstring)",
            "limits_policy": {"path": "deploy/ot-pilot/limits.json", "sha256": digest,
                              "signer_kid": kid},
            "inputs": inputs,
            "measures": H.measures(rows, [s["shift_id"] for s in shifts]),
            "writes": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("shifts", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(args.shifts)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m = result["measures"]
    print(f"by hand: P1 {m['P1']['shifts_with_a_limit_refusal']}/{m['P1']['of_shifts']}; "
          f"P2 {m['P2']['limit_refusals']}/{m['P2']['of_writes']} "
          f"(bootstrap 95 % {m['P2']['bootstrap_95'][0]:.3f} to {m['P2']['bootstrap_95'][1]:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
