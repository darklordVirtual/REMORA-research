#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every active safety claim states its utility cost (claim register).

A false-accept rate of zero says nothing on its own: a gate that refuses every
call reaches it trivially. AgentHarm showed exactly that (FAR 0/208 with every
benign twin blocked), and the BFCL C-ext3 run met its safety targets while read
autonomy stayed at 26.6% against a 75% bar. Both were published, but as prose.
This gate makes the utility side machine-readable.

A claim is a *safety claim* when its metrics include one of ``SAFETY_METRICS``.
Each active safety claim must declare either

``utility_floors``        a list of pre-registered utility bars, each with
                          ``metric`` (a key in the claim's ``metrics`` that is
                          bound to an artifact in ``metric_bindings``), exactly
                          one of ``min`` or ``max``, ``source`` (the committed
                          file where the bar was fixed), and ``status``
                          (``met`` or ``missed``), or
``utility_floor_exempt``  a reason no utility floor applies.

The gate recomputes each floor's status from the claim's metric value and fails
when the declared status disagrees. It reads the value from ``metrics``, not the
artifact: ``check_claim_metric_bindings.py`` already proves the two agree, and
this gate refuses a floor on an unbound metric so that proof always exists.

    python scripts/check_claim_utility_floors.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs" / "assurance" / "claim_register_v1.yaml"

#: Metric keys that make a claim a safety claim. A new false-accept style
#: metric name belongs here, or the claim it appears in escapes the gate.
SAFETY_METRICS = frozenset({
    "far_pct",
    "wrong_call_accept_pct",
    "false_accept_rate_full",
    "corrupt_accept_rate",
})

STATUSES = ("met", "missed")


def _floor_errors(claim_id: str, claim: dict[str, Any], floor: dict[str, Any],
                  root: Path) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    metric = floor.get("metric")
    metrics = claim.get("metrics") or {}
    if metric not in metrics:
        return [f"{claim_id}: utility floor names {metric}, which is not in "
                "the claim's metrics"], None
    binding = (claim.get("metric_bindings") or {}).get(metric) or {}
    if "path" not in binding and "derived" not in binding:
        return [f"{claim_id}: utility floor on {metric}, which is not bound "
                "to an artifact; a floor must be checkable"], None
    bounds = [key for key in ("min", "max") if floor.get(key) is not None]
    if len(bounds) != 1:
        return [f"{claim_id}: utility floor on {metric} needs exactly one of "
                "'min' or 'max'"], None
    source = str(floor.get("source") or "").strip()
    if not source:
        errors.append(f"{claim_id}: utility floor on {metric} names no source")
    elif not (root / source).exists():
        errors.append(f"{claim_id}: utility floor source {source} does not exist")
    declared = floor.get("status")
    if declared not in STATUSES:
        errors.append(f"{claim_id}: utility floor on {metric}: status must be "
                      f"one of {STATUSES}, not {declared!r}")

    value = float(metrics[metric])
    bound = bounds[0]
    bar = float(floor[bound])
    met = value >= bar if bound == "min" else value <= bar
    computed = "met" if met else "missed"
    op = ">=" if bound == "min" else "<="
    if declared in STATUSES and declared != computed:
        errors.append(f"{claim_id}: utility floor {metric} {op} {bar} is "
                      f"{computed} ({value}), but the register declares "
                      f"{declared!r}")
    row = {"claim": claim_id, "metric": metric, "op": op, "bar": bar,
           "value": value, "status": computed}
    return errors, row


def check(register: dict[str, Any], *, root: Path = ROOT
          ) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    for claim in register.get("claims") or []:
        if claim.get("status") != "active":
            continue
        claim_id = claim.get("id", "?")
        floors = claim.get("utility_floors") or []
        exempt = str(claim.get("utility_floor_exempt") or "").strip()
        safety = sorted(SAFETY_METRICS & set(claim.get("metrics") or {}))
        if safety and not floors and not exempt:
            errors.append(f"{claim_id}: active safety claim ({', '.join(safety)}) "
                          "declares neither utility_floors nor a "
                          "utility_floor_exempt reason")
        for floor in floors:
            floor_errors, row = _floor_errors(claim_id, claim, floor, root)
            errors.extend(floor_errors)
            if row is not None:
                rows.append(row)
    return errors, rows


def main() -> int:
    import yaml

    register = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    errors, rows = check(register)
    for row in rows:
        print(f"  {row['claim']} {row['metric']} {row['op']} {row['bar']}: "
              f"{row['value']} -> {row['status'].upper()}")
    if errors:
        print("[FAIL] claim utility floors:")
        for error in errors:
            print(f"  - {error}")
        return 1
    missed = sum(1 for row in rows if row["status"] == "missed")
    print(f"[PASS] claim utility floors: {len(rows)} floor(s) declared, "
          f"{missed} missed and published as missed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
