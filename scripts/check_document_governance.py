# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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
  6. Release-gates table — every REM status row in release_gates.md mirrors
     the status held in remediation_register.yaml; the human-readable gate
     register cannot drift from the machine source.
  7. README budget — README.md stays under a line cap so "surface one more
     thing in the README" has an enforced cost.

Exit codes: 0 = all checks pass, 1 = violations (listed on stderr).
Requires PyYAML (dev extra). Uses `git ls-files` so gitignored local files
(e.g. local-only working documents) are out of scope by construction.
"""
from __future__ import annotations

import datetime
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOC_REGISTER = ROOT / "docs" / "assurance" / "document_register_v1.yaml"
RELEASE_GATES = ROOT / "docs" / "assurance" / "release_gates.md"
CAP_REGISTER = ROOT / "docs" / "assurance" / "capability_register_v1.yaml"
REM_REGISTER = ROOT / "docs" / "assurance" / "remediation_register.yaml"
CLAIM_REGISTER = ROOT / "docs" / "assurance" / "claim_register_v1.yaml"
PROFILES = ROOT / "docs" / "assurance" / "release_profiles_v1.yaml"

ALLOWED_STATUSES = {
    "canonical", "generated", "supporting", "proposal", "historical", "superseded",
}
# Schema-v2 verification fields.
ALLOWED_CODE_SYNCED = {"unreviewed", "verified", "mismatch"}
ALLOWED_VERDICTS = {"pending", "current", "fixed", "consolidate", "stale"}
DOC_ID_RE = re.compile(r"DOC-\d+")
VERSION_RE = re.compile(r"v\d+")
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# A document whose content was last verified against code more than this many
# days ago is WARNed (not failed) as due for re-review.
STALE_REVIEW_DAYS = 30
GOVERNED_SUFFIXES = {".md", ".html", ".yaml", ".yml", ".json"}
# Root-level knowledge documents governed alongside docs/. Build/config files
# (Makefile, pyproject.toml, requirements-lock.txt, .gitignore) and the LICENSE
# text are intentionally excluded — they are not narrative knowledge documents.
ROOT_DOCS = (
    "README.md",
    "ARCHITECTURE.md",
    "NEGATIVE_RESULTS.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CONTRIBUTORS.md",
    "CLAUDE.md",
    "EVIDENCE_OF_CAPABILITY.md",
    "NOTICE",
)
# Markers that satisfy the historical-banner requirement (case-insensitive).
HISTORICAL_MARKERS = ("historical", "archived", "snapshot", "superseded", "do not cite")
README_LINE_CAP = 300


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _git_ls(pathspec: str) -> list[str]:
    return subprocess.run(
        ["git", "ls-files", pathspec],
        capture_output=True, text=True, cwd=ROOT, check=True,
    ).stdout.splitlines()


def _tracked_docs() -> list[str]:
    """Governed knowledge documents: docs/ (minus figures/) + paper/*.md +
    an explicit root-doc allowlist."""
    files: set[str] = set()
    for line in _git_ls("docs/") + _git_ls("paper/"):
        p = line.strip()
        if not p or p.startswith("docs/figures/"):
            continue
        if Path(p).suffix.lower() in GOVERNED_SUFFIXES:
            files.add(p)
    for p in ROOT_DOCS:
        if (ROOT / p).exists():
            files.add(p)
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

    # Controlled topic registry: canonical documents may only claim a topic
    # declared here, so near-duplicate free-text topics (architecture vs
    # architecture-narrative vs reference-architecture) cannot proliferate.
    registered_topics = set(reg.get("topics", []))

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
            elif registered_topics and topic not in registered_topics:
                errors.append(
                    f"document-register: {path}: topic {topic!r} is not in the "
                    f"controlled `topics:` registry"
                )
            elif topic in topics:
                errors.append(
                    f"document-register: topic {topic!r} claimed by both "
                    f"{topics[topic]} and {path}"
                )
            else:
                topics[topic] = path
        if status == "historical":
            if (ROOT / path).exists():
                head = "\n".join(
                    (ROOT / path).read_text(encoding="utf-8", errors="ignore")
                    .splitlines()[:15]
                ).lower()
                if not any(m in head for m in HISTORICAL_MARKERS):
                    errors.append(
                        f"document-register: historical {path} lacks a banner in "
                        f"its first 15 lines (one of {sorted(HISTORICAL_MARKERS)})"
                    )
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


def check_document_verification(errors: list[str], warnings: list[str]) -> None:
    """Schema-v2 verification state: every entry carries a stable DOC id, a
    version, and an honest content-vs-code review state. The consistency rules
    below enforce the claim-hygiene invariant that a document may not be marked
    `verified`/`current`/`fixed` without a real review date behind it — the
    register cannot claim a document was checked when it was not."""
    reg = _load(DOC_REGISTER)
    entries = reg.get("documents", [])
    today = datetime.date.today()

    doc_ids: list[str] = []
    for e in entries:
        path = e.get("path", "?")

        did = e.get("id")
        if not (isinstance(did, str) and DOC_ID_RE.fullmatch(did)):
            errors.append(f"document-register: {path}: missing/invalid id {did!r} (want DOC-NNN)")
        else:
            doc_ids.append(did)

        ver = e.get("version")
        if not (isinstance(ver, str) and VERSION_RE.fullmatch(ver)):
            errors.append(f"document-register: {path}: missing/invalid version {ver!r} (want vN)")

        cs = e.get("code_synced")
        if cs not in ALLOWED_CODE_SYNCED:
            errors.append(f"document-register: {path}: code_synced {cs!r} not in {sorted(ALLOWED_CODE_SYNCED)}")

        vd = e.get("verdict")
        if vd not in ALLOWED_VERDICTS:
            errors.append(f"document-register: {path}: verdict {vd!r} not in {sorted(ALLOWED_VERDICTS)}")

        lr = e.get("last_reviewed")
        reviewed_on: datetime.date | None = None
        if lr is not None:
            if not (isinstance(lr, (str, datetime.date)) and ISO_DATE_RE.fullmatch(str(lr))):
                errors.append(f"document-register: {path}: last_reviewed {lr!r} is not an ISO date or null")
            else:
                try:
                    reviewed_on = datetime.date.fromisoformat(str(lr))
                except ValueError:
                    errors.append(f"document-register: {path}: last_reviewed {lr!r} is not a valid date")

        # Anti-fake-checked consistency: a verified/current/fixed claim requires
        # a real review date.
        if cs == "verified" and reviewed_on is None:
            errors.append(f"document-register: {path}: code_synced=verified but last_reviewed is null")
        if vd in {"current", "fixed"} and cs != "verified":
            errors.append(f"document-register: {path}: verdict={vd} requires code_synced=verified (got {cs!r})")

        # Non-failing review-hygiene signals.
        if reviewed_on is None:
            warnings.append(f"document-register: {path}: never audited against code (last_reviewed null)")
        elif (today - reviewed_on).days > STALE_REVIEW_DAYS:
            warnings.append(
                f"document-register: {path}: last_reviewed {lr} is "
                f"{(today - reviewed_on).days}d old (> {STALE_REVIEW_DAYS}d) — due for re-review"
            )

    for dup in sorted({i for i in doc_ids if doc_ids.count(i) > 1}):
        errors.append(f"document-register: duplicate DOC id {dup}")


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


def _norm_status(s: str) -> str:
    """Collapse a status token/cell to comparable letters (drops markdown,
    spaces, underscores, punctuation, case): 'NOT STARTED' == 'NOT_STARTED'."""
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def check_release_gates_table(errors: list[str]) -> None:
    """release_gates.md is the human-readable gate register; its Status column is
    a *mirror* of remediation_register.yaml (the machine source). Parse every
    table row whose first cell is a REM id and assert its Status cell states the
    register's status, so the mirror cannot silently drift. History/prose tables
    (Date-keyed elevation log, AII-range table) are skipped: their first cell is
    not a REM id."""
    if not RELEASE_GATES.exists():
        errors.append("release-gates: docs/assurance/release_gates.md is missing")
        return
    rems = _rem_statuses()
    checked = 0
    for line in RELEASE_GATES.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        rid_match = re.fullmatch(r"\**\s*(REM-\d+)\s*\**", cells[0])
        if not rid_match:
            continue
        rid = rid_match.group(1)
        status_cell = cells[2]
        if rid not in rems:
            errors.append(
                f"release-gates: row for {rid} has no entry in "
                f"remediation_register.yaml"
            )
            continue
        want = _norm_status(rems[rid])
        if want not in _norm_status(status_cell):
            errors.append(
                f"release-gates: {rid} Status cell {status_cell!r} does not "
                f"state the register status {rems[rid]!r} — the table has "
                f"drifted from remediation_register.yaml (the register wins)"
            )
        checked += 1
    if checked == 0:
        errors.append(
            "release-gates: no REM status rows found to verify — the table "
            "structure changed; update check_release_gates_table"
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
    warnings: list[str] = []
    check_document_register(errors)
    check_document_verification(errors, warnings)
    check_register_id_uniqueness(errors)
    check_release_profiles(errors)
    check_release_gates_table(errors)
    check_readme_budget(errors)
    if warnings:
        for w in warnings:
            print(f"WARN: {w}", file=sys.stderr)
        print(f"documentation governance: {len(warnings)} review-hygiene warning(s)", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print(f"\ndocumentation governance: {len(errors)} violation(s)", file=sys.stderr)
        return 1
    print("documentation governance: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
