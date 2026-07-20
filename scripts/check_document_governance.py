# Author: Stian Skogbrott
# License: Apache-2.0
"""Documentation-governance gate.

Validates that the repository's documentation behaves as a governed system,
with the registers as the single sources of truth:

  1. Document register coverage — every tracked file under docs/ (figures/
     excluded) has exactly one entry in
     docs/assurance/document_register_v1.yaml, and every entry points to an
     existing tracked file.
  2. Status discipline — statuses come from the fixed enum; `superseded`
     entries name an existing successor and the stub itself points to it;
     `generated` entries name an existing generator.
  3. Canonical uniqueness — at most one canonical document per topic.
  4. Register ID uniqueness — CAP-*/REM-*/CLAIM-* ids are unique within
     their registers.
  5. Release profiles — every referenced CAP/REM id exists, every required
     level is on the capability ladder, and the DECLARED current_profile
     equals the profile recomputed from the capability and remediation
     registers. A profile cannot be claimed by editing prose.
  6. README budget — README.md stays under a line cap so "surface one more
     thing in the README" has an enforced cost.

Exit codes: 0 = all checks pass, 1 = violations (listed on stderr).
Requires PyYAML (dev extra). Uses `git ls-files` so gitignored local files
(e.g. local-only working documents) are out of scope by construction.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOC_REGISTER = ROOT / "docs" / "assurance" / "document_register_v1.yaml"
CAP_REGISTER = ROOT / "docs" / "assurance" / "capability_register_v1.yaml"
REM_REGISTER = ROOT / "docs" / "assurance" / "remediation_register.yaml"
CLAIM_REGISTER = ROOT / "docs" / "assurance" / "claim_register_v1.yaml"
PROFILES = ROOT / "docs" / "assurance" / "release_profiles_v1.yaml"

ALLOWED_STATUSES = {
    "canonical", "generated", "supporting", "proposal", "historical", "superseded",
}
GOVERNED_SUFFIXES = {".md", ".html", ".yaml", ".yml", ".json"}
README_LINE_CAP = 400


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _tracked_docs() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "docs/"],
        capture_output=True, text=True, cwd=ROOT, check=True,
    ).stdout
    files = []
    for line in out.splitlines():
        p = line.strip()
        if not p or p.startswith("docs/figures/"):
            continue
        if Path(p).suffix.lower() in GOVERNED_SUFFIXES:
            files.append(p)
    return sorted(files)


def check_document_register(errors: list[str]) -> None:
    reg = _load(DOC_REGISTER)
    entries = reg.get("documents", [])
    tracked = _tracked_docs()

    paths = [e.get("path", "") for e in entries]
    dupes = {p for p in paths if paths.count(p) > 1}
    for p in sorted(dupes):
        errors.append(f"document-register: duplicate entry for {p}")

    registered = set(paths)
    for p in tracked:
        if p not in registered:
            errors.append(f"document-register: tracked file has no entry: {p}")
    for p in sorted(registered - set(tracked)):
        errors.append(f"document-register: entry for missing/untracked file: {p}")

    topics: dict[str, str] = {}
    for e in entries:
        path, status = e.get("path", "?"), e.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"document-register: {path}: invalid status {status!r}")
            continue
        if status == "canonical":
            topic = e.get("topic")
            if not topic:
                errors.append(f"document-register: {path}: canonical without topic")
            elif topic in topics:
                errors.append(
                    f"document-register: topic {topic!r} claimed by both "
                    f"{topics[topic]} and {path}"
                )
            else:
                topics[topic] = path
        if status == "superseded":
            successor = e.get("superseded_by")
            if not successor or not (ROOT / successor).exists():
                errors.append(
                    f"document-register: {path}: superseded_by missing or "
                    f"nonexistent ({successor!r})"
                )
            elif (ROOT / path).exists():
                stub = (ROOT / path).read_text(encoding="utf-8", errors="ignore")
                if Path(successor).name not in stub:
                    errors.append(
                        f"document-register: superseded {path} does not point "
                        f"readers to {Path(successor).name}"
                    )
        if status == "generated":
            gen = e.get("generated_by")
            if not gen or not (ROOT / gen).exists():
                errors.append(
                    f"document-register: {path}: generated_by missing or "
                    f"nonexistent ({gen!r})"
                )


def _collect_ids(data, pattern: re.Pattern) -> list[str]:
    found: list[str] = []
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            val = node.get("id")
            if isinstance(val, str) and pattern.fullmatch(val):
                found.append(val)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


def check_register_id_uniqueness(errors: list[str]) -> None:
    for path, pat in (
        (CAP_REGISTER, re.compile(r"CAP-\d+")),
        (REM_REGISTER, re.compile(r"REM-\d+")),
        (CLAIM_REGISTER, re.compile(r"CLAIM-\d+")),
    ):
        ids = _collect_ids(_load(path), pat)
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            errors.append(f"{path.name}: duplicate register id {dup}")


def _rem_statuses() -> dict[str, str]:
    reg = _load(REM_REGISTER)
    out: dict[str, str] = {}
    stack = [reg]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            rid, status = node.get("id"), node.get("status")
            if isinstance(rid, str) and rid.startswith("REM-") and status is not None:
                out[rid] = str(status).strip()
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def _rem_gates() -> dict[str, str]:
    reg = _load(REM_REGISTER)
    out: dict[str, str] = {}
    stack = [reg]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            rid, gate = node.get("id"), node.get("gate")
            if isinstance(rid, str) and rid.startswith("REM-") and gate is not None:
                out[rid] = str(gate).strip()
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def check_release_profiles(errors: list[str]) -> None:
    prof = _load(PROFILES)
    ladder: list[str] = prof["capability_ladder"]
    prefixes: list[str] = prof["rem_satisfied_prefixes"]
    declared = prof["current_profile"]

    caps = {c["id"]: c["status"] for c in _load(CAP_REGISTER)["capabilities"]}
    for cid, level in caps.items():
        if level not in ladder:
            errors.append(
                f"release-profiles: capability register {cid} has level "
                f"{level!r} not on the declared ladder"
            )
    rems = _rem_statuses()
    gates = _rem_gates()

    def rem_ok(rid: str) -> bool:
        status = rems.get(rid, "")
        return any(status.upper().startswith(p) for p in prefixes)

    def cap_ok(cid: str, required: str) -> bool:
        return ladder.index(caps[cid]) >= ladder.index(required)

    by_name = {p["name"]: p for p in prof["profiles"]}
    satisfied: dict[str, bool] = {}

    for p in sorted(prof["profiles"], key=lambda x: x["order"]):
        ok = True
        parent = p.get("includes")
        if parent:
            if parent not in satisfied:
                errors.append(
                    f"release-profiles: {p['name']} includes {parent!r} which "
                    f"is not an earlier profile"
                )
                ok = False
            else:
                ok = satisfied[parent]
        for rid in p.get("requires", {}).get("rem_done", []) or []:
            if rid not in rems:
                errors.append(f"release-profiles: {p['name']}: unknown {rid}")
                ok = False
            elif not rem_ok(rid):
                ok = False
        for cid, level in (p.get("requires", {}).get("capabilities") or {}).items():
            if cid not in caps:
                errors.append(f"release-profiles: {p['name']}: unknown {cid}")
                ok = False
            elif level not in ladder:
                errors.append(
                    f"release-profiles: {p['name']}: {cid} level {level!r} "
                    f"not on ladder"
                )
                ok = False
            elif not cap_ok(cid, level):
                ok = False
        max_gate = p.get("requires", {}).get("all_rem_items_with_gate_at_most")
        if max_gate:
            limit = int(max_gate.lstrip("P"))
            for rid, gate in gates.items():
                m = re.fullmatch(r"P(\d+)", gate)
                if m and int(m.group(1)) <= limit and not rem_ok(rid):
                    ok = False
        satisfied[p["name"]] = ok

    computed = None
    for p in sorted(prof["profiles"], key=lambda x: x["order"]):
        if satisfied.get(p["name"]):
            computed = p["name"]
    if declared not in by_name:
        errors.append(f"release-profiles: declared current_profile {declared!r} unknown")
    elif computed != declared:
        errors.append(
            f"release-profiles: declared current_profile is {declared} but the "
            f"registers compute {computed} — update register state (with "
            f"evidence), not the declaration"
        )


def check_readme_budget(errors: list[str]) -> None:
    n = len((ROOT / "README.md").read_text(encoding="utf-8").splitlines())
    if n > README_LINE_CAP:
        errors.append(
            f"README.md is {n} lines (cap {README_LINE_CAP}): move detail into "
            f"docs/ and link it; the README is a surface, not a store"
        )


def main() -> int:
    errors: list[str] = []
    check_document_register(errors)
    check_register_id_uniqueness(errors)
    check_release_profiles(errors)
    check_readme_budget(errors)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print(f"\ndocumentation governance: {len(errors)} violation(s)", file=sys.stderr)
        return 1
    print("documentation governance: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
