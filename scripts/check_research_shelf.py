#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Gate for docs/research/research_shelf_v1.yaml.

A shelf of research components is only useful if picking something off it
carries its grounding along. Left unchecked, three failures arrive on their
own: a source nobody retrieved gets adopted anyway, an "ADOPTED" entry names
a module that was renamed or never written, and someone else's headline
number drifts into reading like a REMORA result.

This script refuses all three. It is deliberately structural — it does not
fetch URLs and does not judge research quality. It enforces that what the file
*claims about itself* is internally consistent and backed by files on disk.

Exit codes: 0 = shelf is sound, 1 = at least one violation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
SHELF = _REPO_ROOT / "docs" / "research" / "research_shelf_v1.yaml"

VERIFICATION_LADDER = {
    "VERIFIED_RETRIEVED",
    "UNVERIFIED",
    "RETRIEVAL_FAILED",
    "INTERNAL",
}
ADOPTION_LADDER = {
    "ADOPTED",
    "PARTIAL",
    "SCOPED",
    "PROTOTYPE_ONLY",
    "DECLINED",
    "UNEVALUATED",
}

#: Adoption states that assert working code exists, so they must name it.
REQUIRES_EVIDENCE = {"ADOPTED", "PARTIAL"}

#: Adoption states that assert the component is in use. An unverified source
#: must not reach these: adopting research nobody checked is the failure this
#: whole file exists to prevent.
REQUIRES_VERIFIED_SOURCE = {"ADOPTED", "PARTIAL", "SCOPED", "PROTOTYPE_ONLY"}

REQUIRED_COMPONENT_KEYS = {"id", "name", "source", "remora_status", "adoption"}
REQUIRED_SOURCE_KEYS = {"title", "authors", "venue", "verification", "reported_results"}

#: Keys that would record a REMORA measurement here. Those belong in
#: docs/assurance/claim_register_v1.yaml, bound to an artifact on disk.
FORBIDDEN_SOURCE_KEYS = {"remora_results", "remora_accuracy", "our_results"}


def _violations(shelf: dict) -> list[str]:
    problems: list[str] = []
    components = shelf.get("components")
    if not isinstance(components, list) or not components:
        return ["shelf has no components list"]

    seen_ids: set[str] = set()
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            problems.append(f"component[{index}] is not a mapping")
            continue

        cid = str(component.get("id", f"index-{index}"))
        missing = REQUIRED_COMPONENT_KEYS - set(component)
        if missing:
            problems.append(f"{cid}: missing required key(s) {sorted(missing)}")
            continue

        if cid in seen_ids:
            problems.append(f"{cid}: duplicate id")
        seen_ids.add(cid)

        source = component["source"]
        if not isinstance(source, dict):
            problems.append(f"{cid}: 'source' must be a mapping")
            continue

        forbidden = FORBIDDEN_SOURCE_KEYS & set(source)
        if forbidden:
            problems.append(
                f"{cid}: {sorted(forbidden)} record a REMORA measurement; those "
                f"belong in the claim register bound to a result artifact, "
                f"never on the research shelf"
            )

        missing_source = REQUIRED_SOURCE_KEYS - set(source)
        if missing_source:
            problems.append(f"{cid}: source missing {sorted(missing_source)}")
            continue

        verification = str(source["verification"])
        if verification not in VERIFICATION_LADDER:
            problems.append(
                f"{cid}: verification {verification!r} is not on the ladder "
                f"{sorted(VERIFICATION_LADDER)}"
            )
            continue

        adoption = str(component["adoption"])
        if adoption not in ADOPTION_LADDER:
            problems.append(
                f"{cid}: adoption {adoption!r} is not on the ladder "
                f"{sorted(ADOPTION_LADDER)}"
            )
            continue

        # An external work needs a URL; an internal finding must not carry one,
        # so it cannot borrow authority it does not have.
        if verification == "INTERNAL":
            if source.get("url"):
                problems.append(
                    f"{cid}: INTERNAL entries must not cite a url — an internal "
                    f"finding cannot borrow an external work's authority"
                )
            if str(source.get("venue")) != "internal":
                problems.append(f"{cid}: INTERNAL entries need venue: internal")
        elif not str(source.get("url", "")).strip():
            problems.append(f"{cid}: external source has no url")

        if verification == "VERIFIED_RETRIEVED" and not str(
            source.get("verified", "")
        ).strip():
            problems.append(
                f"{cid}: VERIFIED_RETRIEVED requires a 'verified' date naming "
                f"when the record was checked"
            )

        if adoption in REQUIRES_VERIFIED_SOURCE and verification in {
            "UNVERIFIED",
            "RETRIEVAL_FAILED",
        }:
            problems.append(
                f"{cid}: adoption {adoption} on a {verification} source — a work "
                f"nobody retrieved must stay UNEVALUATED or DECLINED"
            )

        if adoption == "DECLINED" and not str(
            component.get("decline_reason", "")
        ).strip():
            problems.append(f"{cid}: DECLINED requires a decline_reason")

        if adoption in REQUIRES_EVIDENCE:
            evidence = component.get("remora_evidence") or []
            if not evidence:
                problems.append(
                    f"{cid}: adoption {adoption} claims shipped code but names "
                    f"no remora_evidence"
                )
            for path in evidence:
                if not (_REPO_ROOT / str(path)).exists():
                    problems.append(
                        f"{cid}: remora_evidence path does not exist: {path}"
                    )
            if not any("test" in str(p) for p in evidence):
                problems.append(
                    f"{cid}: adoption {adoption} names no test among its "
                    f"evidence; shipped means tested"
                )

        blocked_by = component.get("blocked_by")
        if blocked_by and str(blocked_by) not in {
            str(c.get("id")) for c in components if isinstance(c, dict)
        }:
            problems.append(f"{cid}: blocked_by {blocked_by!r} is not a shelf id")

    return problems


def main() -> int:
    if not SHELF.exists():
        print(f"[FAIL] research shelf not found: {SHELF}", file=sys.stderr)
        return 1

    shelf = yaml.safe_load(SHELF.read_text(encoding="utf-8"))
    problems = _violations(shelf)

    components = shelf.get("components") or []
    if problems:
        print(f"[FAIL] research shelf: {len(problems)} violation(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    by_adoption: dict[str, int] = {}
    unverified = 0
    for component in components:
        by_adoption[component["adoption"]] = by_adoption.get(component["adoption"], 0) + 1
        if component["source"]["verification"] == "UNVERIFIED":
            unverified += 1

    print(f"[OK] research shelf: {len(components)} component(s)")
    for state in sorted(by_adoption):
        print(f"       {state:<16} {by_adoption[state]}")
    if unverified:
        print(
            f"       {unverified} source(s) still UNVERIFIED — pickable only "
            f"after retrieval; not citable in narrative docs."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
