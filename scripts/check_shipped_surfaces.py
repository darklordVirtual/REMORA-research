#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Bind the shipped-surfaces matrix to the workflows that actually run.

``docs/assurance/shipped_surfaces_v1.yaml`` names every advertised surface and
the CI jobs that guard it (issue #84). A matrix that nothing validates would
drift the first time a workflow was renamed: the register would keep claiming
a contract that no longer runs, which is precisely the failure a
shipped-surfaces statement exists to prevent.

Hard checks:

* every ``job`` reference (``<workflow-file>:<job-id>``) resolves to a real
  job in ``.github/workflows/`` — job *ids*, not display names, because ids
  survive renames;
* every surface carries at least one ``smoke`` contract and at least one of
  ``type``/``lint``/``test`` — a surface with no functional check is
  advertised, not shipped;
* the surface count never drops below ``surface_baseline`` — the matrix is
  additive (issue #84 residual 3), so a surface cannot quietly stop being
  checked by being deleted here. Retiring one means lowering the baseline in
  the same change, visibly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "shipped_surfaces_v1.yaml"
WORKFLOWS = ROOT / ".github" / "workflows"

ALLOWED_KINDS = {"smoke", "lint", "type", "test", "artifact", "audit"}
FUNCTIONAL_KINDS = {"type", "lint", "test"}


def workflow_jobs() -> dict[str, set[str]]:
    """Map workflow file name -> set of job ids."""
    jobs: dict[str, set[str]] = {}
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        try:
            data = yaml.safe_load(wf.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:  # a broken workflow is its own failure
            raise SystemExit(f"[FAIL] {wf.name}: unparseable workflow: {exc}")
        jobs[wf.name] = set((data.get("jobs") or {}).keys())
    return jobs


def main() -> int:
    register = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    surfaces = register.get("surfaces") or []
    baseline = int(register.get("surface_baseline", 0))
    jobs = workflow_jobs()

    errors: list[str] = []
    names: list[str] = []
    for surface in surfaces:
        name = str(surface.get("name", "")).strip()
        if not name:
            errors.append("surface with no name")
            continue
        names.append(name)
        contracts = surface.get("contracts") or []
        kinds = {str(c.get("kind")) for c in contracts}
        unknown = kinds - ALLOWED_KINDS
        if unknown:
            errors.append(f"{name}: unknown contract kind(s) {sorted(unknown)}")
        if "smoke" not in kinds:
            errors.append(f"{name}: no smoke contract — advertised, not shipped")
        if not (kinds & FUNCTIONAL_KINDS):
            errors.append(
                f"{name}: no type/lint/test contract — nothing checks it works"
            )
        for contract in contracts:
            ref = str(contract.get("job", ""))
            if ":" not in ref:
                errors.append(f"{name}: malformed job reference {ref!r}")
                continue
            wf, job_id = ref.split(":", 1)
            if wf not in jobs:
                errors.append(f"{name}: {ref!r} names workflow {wf!r} which does not exist")
            elif job_id not in jobs[wf]:
                errors.append(
                    f"{name}: {ref!r} names job {job_id!r} which is not in {wf} "
                    f"(has: {sorted(jobs[wf])})"
                )

    if len(set(names)) != len(names):
        errors.append("duplicate surface names")
    if len(names) < baseline:
        errors.append(
            f"surface count {len(names)} fell below the baseline {baseline}: "
            f"retiring a surface must lower the baseline in the same change"
        )

    if errors:
        print("[FAIL] shipped-surfaces matrix:", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"[PASS] shipped-surfaces: {len(names)} surface(s), every contract "
          f"resolves to a live workflow job.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
