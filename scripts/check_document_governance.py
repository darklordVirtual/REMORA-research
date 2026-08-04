# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Documentation-governance gate.

Validates that the repository's documentation behaves as a governed system,
with the registers as the single sources of truth. As of the 2026-07-27
loosening, the checks split into two tiers:

  HARD (fail CI) — structural integrity that must never drift:
    * Status discipline — statuses come from the fixed enum; `superseded`
      entries name an existing successor and the stub itself points to it;
      `historical` entries carry a banner; `generated` entries name an
      existing generator.
    * Canonical uniqueness — at most one canonical document per topic, drawn
      from the controlled `topics:` registry.
    * Register ID uniqueness — CAP-*/REM-*/CLAIM-*/DOC-* ids are unique.
    * Release profiles — the DECLARED current_profile equals the profile
      recomputed from the capability and remediation registers.
    * Release-gates table — every REM status row in release_gates.md mirrors
      remediation_register.yaml.

  ADVISORY (warn only, never fail) — review hygiene, not correctness:
    * Document-register coverage (a tracked file with no entry, or an entry
      for a missing file). Adding a doc no longer breaks the build.
    * Schema-v2 verification fields (id/version/code_synced/verdict) and the
      verified/verdict consistency signals. A document may be edited without
      re-stamping its verification state.
    * README line budget (soft cap advisory; hard cap is a HARD violation).

  There is intentionally NO time-based staleness clock: documents are not
  nagged for "aging" against an arbitrary review window.

Exit codes: 0 = all HARD checks pass (advisory warnings may print),
1 = HARD violations (listed on stderr). Requires PyYAML (dev extra). Uses
`git ls-files` so gitignored local files are out of scope by construction.
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
# Schema-v2 verification fields (advisory).
ALLOWED_CODE_SYNCED = {"unreviewed", "verified", "mismatch"}
ALLOWED_VERDICTS = {"pending", "current", "fixed", "consolidate", "stale"}
DOC_ID_RE = re.compile(r"DOC-\d+")
VERSION_RE = re.compile(r"v\d+")
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
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
# Statuses that present a document as live knowledge. A live document whose
# entire content is a bare placeholder stub is a HARD violation: either the
# content must be restored or the entry moved to historical/superseded (which
# carry their own stub semantics).
LIVE_STATUSES = {"canonical", "generated", "supporting", "proposal"}
PLACEHOLDER_RE = re.compile(r"^#*\s*placeholder[.!]?\s*$", re.IGNORECASE)
# Two-level front-page budget (2026-08-04 README simplification): above the
# soft cap CI prints an advisory hint; above the hard cap CI FAILS. The front
# page is a landing page, not the project dossier — detail belongs in docs/
# with a link from the README.
README_LINE_SOFT_CAP = 160
README_LINE_HARD_CAP = 200


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


def check_document_register(errors: list[str], warnings: list[str]) -> None:
    reg = _load(DOC_REGISTER)
    entries = reg.get("documents", [])
    tracked = _tracked_docs()

    # Coverage is ADVISORY: adding/removing a doc no longer fails the build.
    paths = [e.get("path", "") for e in entries]
    dupes = {p for p in paths if paths.count(p) > 1}
    for p in sorted(dupes):
        warnings.append(f"document-register: duplicate entry for {p}")

    registered = set(paths)
    for p in tracked:
        if p not in registered:
            warnings.append(f"document-register: tracked file has no entry: {p}")
    for p in sorted(registered - set(tracked)):
        warnings.append(f"document-register: entry for missing/untracked file: {p}")

    # Controlled topic registry: canonical documents may only claim a topic
    # declared here, so near-duplicate free-text topics cannot proliferate.
    # Status/topic/successor discipline stays HARD — this is structural
    # integrity, not review hygiene.
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
        if status in LIVE_STATUSES and (ROOT / path).is_file():
            body = (ROOT / path).read_text(encoding="utf-8", errors="ignore").strip()
            if not body or PLACEHOLDER_RE.fullmatch(body):
                errors.append(
                    f"document-register: {path}: registered as {status!r} but its "
                    f"content is a bare placeholder stub — restore the content or "
                    f"re-register it as historical/superseded"
                )
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
    """Schema-v2 verification state is ADVISORY. Missing/invalid id, version,
    code_synced or verdict, and the verified/verdict consistency signals, are
    reported as warnings so honest review state is encouraged without turning
    every doc edit into a re-stamping chore. The only HARD rule kept here is
    DOC-id uniqueness (a real integrity invariant). There is no time-based
    staleness clock."""
    reg = _load(DOC_REGISTER)
    entries = reg.get("documents", [])

    doc_ids: list[str] = []
    never_audited = 0
    for e in entries:
        path = e.get("path", "?")

        did = e.get("id")
        if not (isinstance(did, str) and DOC_ID_RE.fullmatch(did)):
            warnings.append(f"document-register: {path}: missing/invalid id {did!r} (want DOC-NNN)")
        else:
            doc_ids.append(did)

        ver = e.get("version")
        if not (isinstance(ver, str) and VERSION_RE.fullmatch(ver)):
            warnings.append(f"document-register: {path}: missing/invalid version {ver!r} (want vN)")

        cs = e.get("code_synced")
        if cs not in ALLOWED_CODE_SYNCED:
            warnings.append(f"document-register: {path}: code_synced {cs!r} not in {sorted(ALLOWED_CODE_SYNCED)}")

        vd = e.get("verdict")
        if vd not in ALLOWED_VERDICTS:
            warnings.append(f"document-register: {path}: verdict {vd!r} not in {sorted(ALLOWED_VERDICTS)}")

        lr = e.get("last_reviewed")
        reviewed_on: datetime.date | None = None
        if lr is not None:
            if not (isinstance(lr, (str, datetime.date)) and ISO_DATE_RE.fullmatch(str(lr))):
                warnings.append(f"document-register: {path}: last_reviewed {lr!r} is not an ISO date or null")
            else:
                try:
                    reviewed_on = datetime.date.fromisoformat(str(lr))
                except ValueError:
                    warnings.append(f"document-register: {path}: last_reviewed {lr!r} is not a valid date")

        # Consistency signals are advisory nudges toward honest review state.
        if cs == "verified" and reviewed_on is None:
            warnings.append(f"document-register: {path}: code_synced=verified but last_reviewed is null")
        status = e.get("status")
        if status not in {"historical", "superseded"} and vd in {"current", "fixed"} and cs != "verified":
            warnings.append(f"document-register: {path}: verdict={vd} without code_synced=verified (got {cs!r})")

        if reviewed_on is None:
            never_audited += 1

    # Never-audited docs are collapsed into a single advisory line to avoid
    # flooding; the review backlog is a number, not a wall of warnings.
    if never_audited:
        warnings.append(
            f"document-register: {never_audited} document(s) not yet audited "
            f"against code (last_reviewed null) — advisory backlog, not a failure"
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
    register's status, so the mirror cannot silently drift."""
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


#: Documents that are deliberately unreachable from the index. docs/README.md is
#: the index itself; the two earlier SAPs are superseded by v3 and the index
#: states outright that superseded documents are not linked.
INDEX_EXEMPT = {
    "docs/README.md",
    "docs/assurance/statistical_analysis_plan.md",
    "docs/assurance/statistical_analysis_plan_v2.md",
}


def check_index_completeness(errors: list[str]) -> None:
    """Every live, registered document must be reachable from the docs index.

    docs/README.md claims to be "the single authoritative index" and that
    "every linked document is current". Nothing checked the converse, so a new
    document could be registered, pass every gate, and still be invisible to a
    reader working from the index — which is how `superseded_claims.md` and
    `routing_benchmark_v1_design.md` came to sit unlinked. Superseded documents
    stay off the index by design; that is what INDEX_EXEMPT records, and an
    exemption for a document that is *not* superseded has to be argued for in
    this list rather than happening silently.
    """
    index = ROOT / "docs" / "README.md"
    if not index.exists():
        errors.append("docs-index: docs/README.md is missing")
        return
    text = index.read_text(encoding="utf-8")
    linked: set[str] = set()
    for target in re.findall(r"\]\(([^)]+)\)", text):
        target = target.split("#")[0].strip()
        if not target or target.startswith(("http", "mailto:")):
            continue
        try:
            resolved = (ROOT / "docs" / target).resolve().relative_to(ROOT.resolve())
        except (ValueError, OSError):
            continue
        linked.add(resolved.as_posix())

    register = _load(ROOT / "docs" / "assurance" / "document_register_v1.yaml")
    docs = register.get("documents", register) if isinstance(register, dict) else register
    for entry in docs if isinstance(docs, list) else []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.startswith("docs/"):
            continue
        if entry.get("status") not in LIVE_STATUSES:
            continue
        if path in INDEX_EXEMPT or "/archive/" in path:
            continue
        if path not in linked:
            errors.append(
                f"docs-index: {entry.get('id')} {path} is registered "
                f"status={entry.get('status')!r} but is not linked from "
                f"docs/README.md — add it to the index, or add it to "
                f"INDEX_EXEMPT with a reason if it is deliberately unlisted"
            )


def check_readme_budget(errors: list[str], warnings: list[str]) -> None:
    n = len((ROOT / "README.md").read_text(encoding="utf-8").splitlines())
    if n > README_LINE_HARD_CAP:
        errors.append(
            f"README.md is {n} lines, over the hard cap "
            f"{README_LINE_HARD_CAP}: the front page must stay a landing "
            f"page — move detail into docs/ and link it"
        )
    elif n > README_LINE_SOFT_CAP:
        warnings.append(
            f"README.md is {n} lines (soft cap {README_LINE_SOFT_CAP}): consider "
            f"moving detail into docs/ and linking it — advisory, not a failure"
        )


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    check_document_register(errors, warnings)
    check_document_verification(errors, warnings)
    check_register_id_uniqueness(errors)
    check_release_profiles(errors)
    check_release_gates_table(errors)
    check_index_completeness(errors)
    check_readme_budget(errors, warnings)
    if warnings:
        for w in warnings:
            print(f"WARN: {w}", file=sys.stderr)
        print(f"documentation governance: {len(warnings)} advisory warning(s)", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print(f"\ndocumentation governance: {len(errors)} violation(s)", file=sys.stderr)
        return 1
    print("documentation governance: all hard checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
