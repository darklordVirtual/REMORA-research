#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Replay operator shifts through the OT pilot's signed cumulative limits.

    python scripts/run_limits_holdout.py SHIFTS.json [...] --out RESULT.json [--flags FLAGS.json]
        [--policy LIMITS.json --trusted-key HEX] [--approvers N]

The procedure is fixed in docs/assurance/ot_limits_holdout_plan_v1.md §4. The
pilot's limits.json is verified against the key its compose file trusts, with
the API's own functions, and loaded into one fresh LimitGuard and LimitLedger
per shift. The plant is the pilot's own tool code and observer
(deploy/ot-pilot/ot_registry.py), reset to its starting state for each shift.
Each write runs, in time order, through reserve, begin and fence as the
dispatcher calls them, with the clock set to the shift start plus the write's
offset. A refused write is recorded with its reason, is not retried and does
not change the plant. A write that is let through changes the plant, and the
guard settles it with the tool's result.

The measures are those of the plan's §5: P1 (share of shifts with at least one
limit refusal, Wilson 95 %), P2 (share of writes, shift-level bootstrap with
seed 20261105) and the refusals by limit and reason. With --flags, both are
also given without the writes a plausibility reviewer flagged. There is no
score beyond those.

A policy with a limit's second tier (``dual_control_above``) adds one measure:
the writes, and the shifts, that needed a second approver. ``--approvers`` is
how many distinct people approve each write (1 by default: every pilot write
is reviewed by one person). With 1, a write past the tier refuses as
``limit_dual_control_unmet``; with 2, it runs and is counted. ``--policy``
replays under another signed policy, such as a holdout's sealed one. The
recorded holdouts reproduce only under the policy each was sealed with:
v1 and v2 keep theirs in their artifact folders, and v3's is
``artifacts/ot-pilot/limits-holdout-v3/limits-v3.json``. The pilot's current
policy has the PIC-101 tier, so a replay without ``--policy`` measures that
policy, not theirs.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import random
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "deploy" / "ot-pilot"
sys.path.insert(0, str(ROOT))

TENANT, PRINCIPAL = "ot-pilot", "ot-agent"
#: Shift start for the replay clock: 2026-11-02T06:00:00Z. Any fixed start gives
#: the same decisions; the windows are relative.
SHIFT_START = 1793858400.0
SEED, RESAMPLES = 20261105, 10_000
TOOLS = {
    "adjust_setpoint": {"loop": str, "value": (int, float)},
    "set_valve_position": {"valve": str, "position_pct": int},
    "acknowledge_alarm": {"alarm_id": str},
    "create_work_order": {"wo_id": str},
    "close_work_order": {"wo_id": str},
}


class ShiftError(ValueError):
    """A shift file does not follow the author brief's format."""


# ── the pilot's own pieces ───────────────────────────────────────────────────


def _registry():
    spec = importlib.util.spec_from_file_location("holdout_ot_registry", PILOT / "ot_registry.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def trusted_keys() -> list[str]:
    """The limit-policy keys the pilot's compose file trusts."""
    for line in (PILOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("REMORA_LIMITS_TRUSTED_KEYS:"):
            return [k.strip() for k in line.split(":", 1)[1].split(",") if k.strip()]
    raise SystemExit("the pilot's compose file names no REMORA_LIMITS_TRUSTED_KEYS")


def load_policy(path: Path = PILOT / "limits.json", keys: list[str] | None = None):
    """The pilot's policy, verified as the API verifies it, and its file digest."""
    from remora.crypto import SignatureDomain, VerificationKey
    from remora.enforcement.cumulative_limits import LimitPolicy, verify_signed_policy

    raw = path.read_bytes()
    verification = [VerificationKey.from_text(k, {SignatureDomain.LIMIT_POLICY})
                    for k in (keys if keys is not None else trusted_keys())]
    policy, kid = verify_signed_policy(json.loads(raw), verification)
    return LimitPolicy.from_dict(policy), "sha256:" + hashlib.sha256(raw).hexdigest(), kid


# ── shifts ───────────────────────────────────────────────────────────────────


def validate(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get("shifts"), list):
        raise ShiftError("a shift file is an object with a list of shifts")
    seen: set[str] = set()
    for shift in document["shifts"]:
        sid = shift.get("shift_id")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ShiftError(f"shift id {sid!r} is missing or repeated")
        seen.add(sid)
        last = -1
        for i, w in enumerate(shift.get("writes") or []):
            where = f"{sid} write {i}"
            t = w.get("t_min")
            if isinstance(t, bool) or not isinstance(t, int) or not 0 <= t <= 480 or t < last:
                raise ShiftError(f"{where}: t_min must be 0 to 480 and non-decreasing")
            last = t
            shape = TOOLS.get(w.get("tool"))
            args = w.get("args")
            if shape is None or not isinstance(args, dict) or set(args) != set(shape):
                raise ShiftError(f"{where}: unknown tool or wrong arguments")
            for name, kind in shape.items():
                if isinstance(args[name], bool) or not isinstance(args[name], kind):
                    raise ShiftError(f"{where}: {name} has the wrong type")
    return document["shifts"]


def _request_hash(tool: str, args: dict[str, Any]) -> str:
    body = json.dumps([TENANT, tool, args], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ── the replay ───────────────────────────────────────────────────────────────


def replay_shift(shift: dict[str, Any], policy, registry, pristine: dict[str, Any],
                 workdir: Path, approvers: int = 1) -> list[dict[str, Any]]:
    from remora.enforcement.cumulative_limits import LimitGuard, LimitLedger

    registry.PLANT.clear()
    registry.PLANT.update(copy.deepcopy(pristine))
    tools = {name: getattr(registry, name) for name in TOOLS}
    guard = LimitGuard(policy, LimitLedger(workdir / f"{shift['shift_id']}.db"),
                       is_write=lambda tool: tool != "read_sensor",
                       observer=registry.observe_limit_value)
    rows = []
    for i, w in enumerate(shift.get("writes") or []):
        op = f"{shift['shift_id']}:{i:03d}"
        now = SHIFT_START + 60.0 * w["t_min"]
        row = {"shift_id": shift["shift_id"], "index": i, "t_min": w["t_min"],
               "tool": w["tool"], "args": w["args"]}
        if _tiered(policy):
            # Asked as /assess asks it, before the reservation: which limits
            # this write would take past their second tier.
            needs = guard.dual_control(tenant=TENANT, principal=PRINCIPAL,
                                       tool_name=w["tool"], arguments=w["args"], now=now)
            if needs:
                row["dual_control"] = list(needs)
        refusal = guard.reserve(tenant=TENANT, principal=PRINCIPAL, tool_name=w["tool"],
                                arguments=w["args"], operation_id=op,
                                request_hash=_request_hash(w["tool"], w["args"]), now=now,
                                approvers=approvers)
        stage = "reserve"
        if refusal is None:
            refusal, stage = guard.begin(op), "begin"
        if refusal is None:
            refusal, stage = guard.fence(op), "fence"
        if refusal is not None:
            if stage != "reserve":
                guard.release(op)
            rows.append({**row, "outcome": "refused", "reason": str(refusal), "stage": stage,
                         "limits": _limits_named(guard, policy, w)})
            continue
        try:
            result = tools[w["tool"]](w["args"])
        except Exception as exc:  # the plant refused the write itself
            guard.settle(op, False, now=now)
            rows.append({**row, "outcome": "tool_error", "reason": type(exc).__name__})
            continue
        guard.settle(op, True, result=result, now=now)
        rows.append({**row, "outcome": "ran"})
    return rows


def _tiered(policy) -> bool:
    """Whether any limit declares a second tier; a policy without one replays as before."""
    return any(lim.dual_control_above is not None for lim in policy.limits)


def _limits_named(guard, policy, write) -> list[str]:
    """The limit ids that govern this write's quantity and resource."""
    try:
        readings = guard.readings(write["tool"], write["args"])
    except Exception:
        return []
    out = []
    for reading in readings:
        for lim in policy.limits:
            if lim.matches(TENANT, PRINCIPAL, reading.meter.quantity, reading.unit,
                           reading.resource):
                out.append(lim.limit_id)
    return sorted(set(out))


# ── the measures ─────────────────────────────────────────────────────────────


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def _is_limit(row: dict[str, Any]) -> bool:
    return row["outcome"] == "refused" and row["reason"].startswith("limit_")


def measures(rows: list[dict[str, Any]], shift_ids: list[str],
             excluded: set[tuple[str, int]] = frozenset(), dual: bool = False) -> dict[str, Any]:
    kept = [r for r in rows if (r["shift_id"], r["index"]) not in excluded]
    by_shift: dict[str, list[dict[str, Any]]] = {s: [] for s in shift_ids}
    for r in kept:
        by_shift[r["shift_id"]].append(r)
    hit = [s for s, rs in by_shift.items() if any(_is_limit(r) for r in rs)]
    refused = sum(_is_limit(r) for r in kept)
    rng = random.Random(SEED)
    ids = list(by_shift)
    draws = []
    for _ in range(RESAMPLES):
        sample = [ids[rng.randrange(len(ids))] for _ in ids]
        n = sum(len(by_shift[s]) for s in sample)
        k = sum(sum(_is_limit(r) for r in by_shift[s]) for s in sample)
        draws.append(k / n if n else 0.0)
    draws.sort()
    lo, hi = wilson(len(hit), len(ids))
    by_limit: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for r in kept:
        if _is_limit(r):
            by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
            for lim in r.get("limits") or ["(none named)"]:
                by_limit[lim] = by_limit.get(lim, 0) + 1
    out = {
        "shifts": len(ids), "writes": len(kept),
        "P1": {"shifts_with_a_limit_refusal": len(hit), "of_shifts": len(ids),
               "share": len(hit) / len(ids) if ids else 0.0,
               "wilson_95": [lo, hi], "shift_ids": sorted(hit)},
        "P2": {"limit_refusals": refused, "of_writes": len(kept),
               "share": refused / len(kept) if kept else 0.0,
               "bootstrap_95": [draws[int(0.025 * RESAMPLES)],
                                draws[int(0.975 * RESAMPLES) - 1]],
               "resamples": RESAMPLES, "seed": SEED},
        "refusals_by_limit": dict(sorted(by_limit.items())),
        "refusals_by_reason": dict(sorted(by_reason.items())),
        "other_outcomes": {
            "refused_not_by_a_limit": sum(r["outcome"] == "refused" and not _is_limit(r)
                                          for r in kept),
            "tool_error": sum(r["outcome"] == "tool_error" for r in kept)},
    }
    if dual:
        needing = sorted(s for s, rs in by_shift.items() if any(r.get("dual_control") for r in rs))
        lo2, hi2 = wilson(len(needing), len(ids))
        out["D1"] = {"shifts_with_a_write_past_a_second_tier": len(needing),
                     "of_shifts": len(ids),
                     "share": len(needing) / len(ids) if ids else 0.0,
                     "wilson_95": [lo2, hi2], "shift_ids": needing}
        out["D2"] = {"writes_past_a_second_tier": sum(bool(r.get("dual_control")) for r in kept),
                     "of_writes": len(kept)}
    return out


def run(paths: list[Path], flags: Path | None = None, *, policy_path: Path | None = None,
        trusted_key: str | None = None, approvers: int = 1) -> dict[str, Any]:
    if policy_path is not None:
        policy, digest, kid = load_policy(policy_path,
                                          keys=[trusted_key] if trusted_key else None)
    else:
        policy, digest, kid = load_policy()
    dual = _tiered(policy)
    registry = _registry()
    pristine = copy.deepcopy(registry.PLANT)
    shifts, inputs = [], []
    for path in paths:
        data = path.read_bytes()
        inputs.append({"path": path.name, "sha256": hashlib.sha256(data).hexdigest()})
        shifts.extend(validate(json.loads(data)))
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        for shift in shifts:
            rows.extend(replay_shift(shift, policy, registry, pristine, Path(tmp),
                                     approvers=approvers))
    ids = [s["shift_id"] for s in shifts]
    shown = "deploy/ot-pilot/limits.json"
    if policy_path is not None:
        where = policy_path.resolve()
        shown = str(where.relative_to(ROOT)) if where.is_relative_to(ROOT) else where.name
    out = {"procedure": "docs/assurance/ot_limits_holdout_plan_v1.md section 4",
           "limits_policy": {"path": shown, "sha256": digest, "signer_kid": kid},
           **({"approvers_per_write": approvers} if dual else {}),
           "inputs": inputs, "measures": measures(rows, ids, dual=dual), "writes": rows}
    if flags is not None:
        flagged = json.loads(flags.read_text(encoding="utf-8"))
        excluded = {(f["shift_id"], int(f["index"])) for f in flagged.get("flags", [])}
        out["flags"] = {"path": flags.name,
                        "sha256": hashlib.sha256(flags.read_bytes()).hexdigest(),
                        "flagged_writes": len(excluded)}
        out["measures_without_flagged"] = measures(rows, ids, excluded, dual=dual)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("shifts", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--flags", type=Path)
    parser.add_argument("--policy", type=Path, help="a signed policy other than the pilot's")
    parser.add_argument("--trusted-key", help="the key --policy is verified under")
    parser.add_argument("--approvers", type=int, default=1, choices=(1, 2))
    args = parser.parse_args(argv)
    if (args.policy is None) != (args.trusted_key is None):
        parser.error("--policy and --trusted-key go together")
    try:
        result = run(args.shifts, args.flags, policy_path=args.policy,
                     trusted_key=args.trusted_key, approvers=args.approvers)
    except ShiftError as exc:
        print(f"[REFUSED] {exc}", file=sys.stderr)
        return 2
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m = result["measures"]
    print(f"P1 {m['P1']['shifts_with_a_limit_refusal']}/{m['P1']['of_shifts']} shifts "
          f"(Wilson 95 % {m['P1']['wilson_95'][0]:.3f} to {m['P1']['wilson_95'][1]:.3f}); "
          f"P2 {m['P2']['limit_refusals']}/{m['P2']['of_writes']} writes "
          f"(bootstrap 95 % {m['P2']['bootstrap_95'][0]:.3f} to {m['P2']['bootstrap_95'][1]:.3f})")
    if "D1" in m:
        print(f"D1 {m['D1']['shifts_with_a_write_past_a_second_tier']}/{m['D1']['of_shifts']} "
              f"shifts needed a second approver (Wilson 95 % {m['D1']['wilson_95'][0]:.3f} to "
              f"{m['D1']['wilson_95'][1]:.3f}); D2 {m['D2']['writes_past_a_second_tier']}/"
              f"{m['D2']['of_writes']} writes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
