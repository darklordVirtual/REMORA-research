#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Claim provenance gate: the claim register is the single source of truth.

This validator enforces four guardrails, all rooted in
docs/assurance/claim_register_v1.yaml:

1. Register integrity — every claim has required fields and a valid
   evidence level from the taxonomy in docs/assurance/evidence_levels.md.
2. Artifact existence — every artifact path cited by a claim exists on disk
   (CLAUDE.md: "No claims without artifacts").
3. Manifest verification — every SHA-256 entry in
   docs/assurance/artifact_manifest_v1.md is canonical lowercase hex and
   matches the file bytes on disk. Files whose only difference is CRLF
   line endings (Windows working trees) pass with a note.
4. Documentation binding — claim anchors in narrative docs
   (``<!-- claim:CLAIM-004 accuracy_pct coverage_pct n -->``) assert that the
   register's value for each listed metric appears in the paragraph that
   follows the anchor; and any doc line that cites a CLAIM id together with
   an evidence-level term must agree with the register.

Known violations are grandfathered in
docs/assurance/claim_provenance_baseline.json: baselined error ids are
reported as WARN and do not fail the gate; anything new fails with exit 1.
Baseline entries that no longer occur are reported so they can be removed.

Stdlib only — no PyYAML. The register parser handles the restricted subset
of YAML actually used by claim_register_v1.yaml (flat claim items, string
lists, ``key: value`` metric maps, and ``>`` block scalars).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = ROOT / "docs" / "assurance" / "claim_register_v1.yaml"
MANIFEST_PATH = ROOT / "docs" / "assurance" / "artifact_manifest_v1.md"
BASELINE_PATH = ROOT / "docs" / "assurance" / "claim_provenance_baseline.json"

EVIDENCE_LEVELS = (
    "theoretical",
    "internal_simulation",
    "internal_benchmark",
    "regression_tested",
    "externally_benchmarked",
    "independently_replicated",
    "field_observed",
    "externally_validated",
)
REQUIRED_CLAIM_FIELDS = ("id", "title", "evidence_level", "artifact", "caveat")

# Narrative docs scanned for claim anchors and evidence-level citations.
DOC_PATTERNS = (
    "README.md",
    "ARCHITECTURE.md",
    "NEGATIVE_RESULTS.md",
    "EVIDENCE_OF_CAPABILITY.md",
    "docs/*.md",
    "docs/assurance/*.md",
    "paper/*.md",
)
# evidence_levels.md defines the taxonomy and legitimately pairs claim ids
# with levels in explanatory examples; it is not a citation site.
EVIDENCE_CHECK_EXCLUDE = ("docs/assurance/evidence_levels.md",)

# Strings that were corrected repo-wide and must not reappear. Each entry:
# (exact substring, why it is stale). Review-findings documents that quote
# defects verbatim are excluded via STALE_CHECK_EXCLUDE.
STALE_STRINGS = (
    ("eligible close 2026-07-07",
     "REM-020 canonical: 7-day criterion, eligible close no earlier than 2026-07-05"),
    ("Day 25/30",
     "REM-020 uses a 7-day criterion, not a 30-day count"),
    ("Autonomous REMORA, Meta-Emergent Reasoner",
     "canonical AROMER expansion: Autonomous Risk-Oriented Meta-Evaluator and Reasoner"),
    ("Autonomous REMORA Orchestrator",
     "canonical AROMER expansion: Autonomous Risk-Oriented Meta-Evaluator and Reasoner"),
    ("AROMER Intelligence Index",
     "canonical AII expansion: Autonomous Intelligence Index"),
    ("run_external_benchmark_agentharm.py",
     "actual script: scripts/run_agentharm_benchmark.py"),
    ("independent_review_template_v1.md",
     "actual file: docs/assurance/independent_review_protocol_v1.md"),
    ("Zhang & Lee",
     "citation corrected 2026-07-03: arXiv:2502.11347 is Dong & Wang"),
)
STALE_CHECK_EXCLUDE = (
    "docs/assurance/simulated_hostile_review_v1.md",  # findings register; quotes defects verbatim
)

ANCHOR_RE = re.compile(r"<!--\s*claim:(CLAIM-\d{3})((?:\s+[a-z0-9_]+)+)\s*-->")
CLAIM_ID_RE = re.compile(r"\bCLAIM-\d{3}\b")
MANIFEST_ROW_RE = re.compile(
    r"^\|\s*`(?P<path>[^`]+)`\s*\|\s*`(?P<sha>[0-9a-fA-F]{64})`\s*\|\s*(?P<size>\d+)\s*\|"
)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


# ---------------------------------------------------------------------------
# Register parsing (restricted YAML subset, stdlib only)
# ---------------------------------------------------------------------------

def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_scalar(value: str) -> object:
    value = value.strip()
    if value in ("null", "~", ""):
        return None
    unquoted = _strip_quotes(value)
    if unquoted != value:
        return unquoted
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def parse_register(text: str) -> list[dict]:
    """Parse claim_register_v1.yaml into a list of claim dicts.

    Handles exactly the constructs the register uses: ``claims:`` at the top
    level, claim items introduced by ``  - id: ...``, scalar fields, string
    lists (``artifact:``), one-level metric maps (``metrics:``), and folded
    block scalars (``>``) whose content is joined with spaces.
    """
    claims: list[dict] = []
    current: dict | None = None
    lines = text.splitlines()
    i = 0
    in_claims = False
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            i += 1
            continue
        if not in_claims:
            if re.match(r"^claims:\s*$", line):
                in_claims = True
            i += 1
            continue

        item_match = re.match(r"^  - (\w+):\s*(.*)$", line)
        if item_match:
            current = {item_match.group(1): _parse_scalar(item_match.group(2))}
            claims.append(current)
            i += 1
            continue

        field_match = re.match(r"^    (\w+):\s*(.*)$", line)
        if field_match and current is not None:
            key, value = field_match.group(1), field_match.group(2).strip()
            if value in (">", "|", ">-", "|-"):
                block: list[str] = []
                i += 1
                while i < len(lines) and (
                    not lines[i].strip() or lines[i].startswith("      ")
                ):
                    if lines[i].strip():
                        block.append(lines[i].strip())
                    i += 1
                current[key] = " ".join(block)
                continue
            if value == "":
                items: list[str] = []
                mapping: dict[str, object] = {}
                i += 1
                while i < len(lines):
                    nested = lines[i]
                    list_match = re.match(r"^      - (.+)$", nested)
                    map_match = re.match(r"^      (\w+):\s*(.+)$", nested)
                    if list_match:
                        items.append(_strip_quotes(list_match.group(1)))
                    elif map_match:
                        mapping[map_match.group(1)] = _parse_scalar(map_match.group(2))
                    elif not nested.strip():
                        pass
                    else:
                        break
                    i += 1
                current[key] = mapping if mapping else items
                continue
            current[key] = _parse_scalar(value)
            i += 1
            continue
        i += 1
    return claims


# ---------------------------------------------------------------------------
# Checks — each returns a list of (error_id, message) tuples
# ---------------------------------------------------------------------------

def check_register(claims: list[dict]) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    if not claims:
        return [("register-empty", f"{REGISTER_PATH.name}: no claims parsed")]
    for claim in claims:
        cid = claim.get("id", "<missing-id>")
        for field in REQUIRED_CLAIM_FIELDS:
            if field not in claim or claim[field] in (None, "", []):
                errors.append(
                    (
                        f"register-missing-field:{cid}:{field}",
                        f"{cid}: required field '{field}' missing or empty",
                    )
                )
        level = claim.get("evidence_level")
        if level is not None and level not in EVIDENCE_LEVELS:
            errors.append(
                (
                    f"register-bad-level:{cid}",
                    f"{cid}: evidence_level '{level}' not in taxonomy",
                )
            )
    return errors


def check_artifacts(claims: list[dict], root: Path = ROOT) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    for claim in claims:
        cid = claim.get("id", "<missing-id>")
        artifacts = claim.get("artifact") or []
        if isinstance(artifacts, str):
            artifacts = [artifacts]
        for rel in artifacts:
            if not (root / rel).exists():
                errors.append(
                    (
                        f"artifact-missing:{cid}:{rel}",
                        f"{cid}: cited artifact does not exist on disk: {rel}",
                    )
                )
    return errors


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_manifest(
    manifest_text: str, notes: list[str], root: Path = ROOT
) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    for lineno, line in enumerate(manifest_text.splitlines(), start=1):
        row = MANIFEST_ROW_RE.match(line)
        if not row:
            continue
        rel, sha = row.group("path"), row.group("sha")
        if sha != sha.lower():
            errors.append(
                (
                    f"manifest-hash-casing:{rel}",
                    f"artifact_manifest_v1.md:{lineno}: non-canonical hash casing "
                    f"for {rel} (must be lowercase hex; breaks sha256sum comparison)",
                )
            )
        path = root / rel
        if not path.exists():
            errors.append(
                (
                    f"manifest-file-missing:{rel}",
                    f"artifact_manifest_v1.md:{lineno}: manifest lists {rel} "
                    f"but the file does not exist",
                )
            )
            continue
        data = path.read_bytes()
        expected = sha.lower()
        if _sha256(data) == expected:
            continue
        if _sha256(data.replace(b"\r\n", b"\n")) == expected:
            notes.append(
                f"{rel}: working-tree bytes are CRLF; LF-normalized hash matches"
            )
            continue
        errors.append(
            (
                f"manifest-hash-mismatch:{rel}",
                f"artifact_manifest_v1.md:{lineno}: SHA-256 mismatch for {rel} — "
                f"file content differs from the manifested version (LF and CRLF "
                f"forms both checked). Re-verify provenance before updating the "
                f"manifest under a documented protocol.",
            )
        )
    return errors


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _paragraph_after(lines: list[str], anchor_idx: int) -> str:
    j = anchor_idx + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    block: list[str] = []
    while j < len(lines) and lines[j].strip():
        block.append(lines[j])
        j += 1
    return " ".join(block)


def check_doc_anchors(
    doc_path: Path, text: str, claims_by_id: dict[str, dict]
) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    rel = _display_path(doc_path)
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        for match in ANCHOR_RE.finditer(line):
            cid, metric_blob = match.group(1), match.group(2)
            claim = claims_by_id.get(cid)
            if claim is None:
                errors.append(
                    (
                        f"anchor-unknown-claim:{rel}:{cid}",
                        f"{rel}:{idx + 1}: anchor cites unknown claim {cid}",
                    )
                )
                continue
            paragraph = line[match.end():] + " " + _paragraph_after(lines, idx)
            found = {float(tok) for tok in NUMBER_RE.findall(paragraph)}
            metrics = claim.get("metrics") or {}
            for key in metric_blob.split():
                if key == "n":
                    expected = claim.get("n")
                else:
                    expected = metrics.get(key) if isinstance(metrics, dict) else None
                if expected is None:
                    errors.append(
                        (
                            f"anchor-unknown-metric:{rel}:{cid}:{key}",
                            f"{rel}:{idx + 1}: anchor metric '{key}' not defined "
                            f"in register for {cid}",
                        )
                    )
                    continue
                if float(expected) not in found:
                    errors.append(
                        (
                            f"anchor-value-drift:{rel}:{cid}:{key}",
                            f"{rel}:{idx + 1}: register says {cid}.{key}={expected} "
                            f"but that value does not appear in the anchored "
                            f"paragraph — doc and register have drifted",
                        )
                    )
    return errors


def check_stale_strings(doc_path: Path, text: str) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    rel = _display_path(doc_path)
    if rel in STALE_CHECK_EXCLUDE:
        return errors
    for idx, line in enumerate(text.splitlines(), start=1):
        for pattern, reason in STALE_STRINGS:
            if pattern in line:
                errors.append(
                    (
                        f"stale-string:{rel}:{pattern}",
                        f"{rel}:{idx}: stale string {pattern!r} — {reason}",
                    )
                )
    return errors


def check_evidence_citations(
    doc_path: Path, text: str, claims_by_id: dict[str, dict]
) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    rel = _display_path(doc_path)
    if rel in EVIDENCE_CHECK_EXCLUDE:
        return errors
    for idx, line in enumerate(text.splitlines(), start=1):
        cited_ids = CLAIM_ID_RE.findall(line)
        if not cited_ids:
            continue
        cited_levels = [lvl for lvl in EVIDENCE_LEVELS if lvl in line]
        if not cited_levels:
            continue
        for cid in set(cited_ids):
            claim = claims_by_id.get(cid)
            if claim is None:
                continue
            register_level = claim.get("evidence_level")
            for level in cited_levels:
                if level != register_level:
                    errors.append(
                        (
                            f"evidence-level-drift:{rel}:{idx}:{cid}",
                            f"{rel}:{idx}: cites {cid} with evidence level "
                            f"'{level}' but register says '{register_level}'",
                        )
                    )
    return errors


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _load_baseline() -> set[str]:
    if not BASELINE_PATH.exists():
        return set()
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return {entry["error_id"] for entry in data.get("known_violations", [])}


def _doc_paths() -> list[Path]:
    paths: list[Path] = []
    for pattern in DOC_PATTERNS:
        paths.extend(sorted(ROOT.glob(pattern)))
    return [p for p in paths if p.is_file()]


def run() -> int:
    notes: list[str] = []
    errors: list[tuple[str, str]] = []

    if not REGISTER_PATH.exists():
        print(f"[FAIL] missing claim register: {REGISTER_PATH}")
        return 1
    claims = parse_register(REGISTER_PATH.read_text(encoding="utf-8"))
    claims_by_id = {c["id"]: c for c in claims if "id" in c}

    errors.extend(check_register(claims))
    errors.extend(check_artifacts(claims))

    if MANIFEST_PATH.exists():
        errors.extend(check_manifest(MANIFEST_PATH.read_text(encoding="utf-8"), notes))
    else:
        errors.append(("manifest-missing", f"missing manifest: {MANIFEST_PATH}"))

    for doc in _doc_paths():
        text = doc.read_text(encoding="utf-8", errors="replace")
        errors.extend(check_doc_anchors(doc, text, claims_by_id))
        errors.extend(check_evidence_citations(doc, text, claims_by_id))
        errors.extend(check_stale_strings(doc, text))

    baseline = _load_baseline()
    seen_ids = {eid for eid, _ in errors}
    new = [(eid, msg) for eid, msg in errors if eid not in baseline]
    grandfathered = [(eid, msg) for eid, msg in errors if eid in baseline]
    stale = sorted(baseline - seen_ids)

    for note in notes:
        print(f"[NOTE] {note}")
    for eid, msg in grandfathered:
        print(f"[WARN] (baselined) {msg}  [{eid}]")
    for eid in stale:
        print(f"[NOTE] baseline entry no longer occurs, remove it: {eid}")
    if new:
        print("Claim provenance gate FAILED:")
        for eid, msg in new:
            print(f" - {msg}  [{eid}]")
        return 1

    print(
        f"[OK] Claim provenance gate passed: {len(claims)} claims, "
        f"{len(grandfathered)} baselined violation(s), {len(stale)} stale "
        f"baseline entr(y/ies)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
