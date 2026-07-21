# Author: Stian Skogbrott
# License: Apache-2.0
"""Render the research-control matrix from its register.

Reads docs/research/research_control_matrix_v1.yaml and writes the human view
docs/research/research_control_matrix.generated.md. Every `code` and `tests`
path is verified to exist on disk; a moved or deleted file is a hard error, so
the research grounding cannot silently drift.

Usage:
    python scripts/generate_research_control_matrix.py            # write
    python scripts/generate_research_control_matrix.py --check    # verify only

--check regenerates in memory and exits non-zero if the committed file differs
or if any referenced path is missing (used by CI and the test suite).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "research" / "research_control_matrix_v1.yaml"
OUTPUT = ROOT / "docs" / "research" / "research_control_matrix.generated.md"
# Local-only landscape catalogue (gitignored). compendium_refs are validated
# against it WHEN PRESENT and skipped where it is absent (CI), so the check is
# a local drift-guard, never a hard CI dependency on an unpublished file.
COMPENDIUM = ROOT / "docs" / "researchpapers" / "kompendium_ai_assurance_3utgave.md"
_REF_RE = re.compile(r"[a-z0-9][a-z0-9-]*")

REQUIRED_FIELDS = (
    "id", "title", "source", "concepts", "controls", "code", "tests",
    "evidence", "maturity", "scope_boundary", "related_work_section",
    "in_code_citation",
)


def _load() -> dict:
    with open(REGISTER, encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate(data: dict) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors: list[str] = []
    levels = set(data.get("maturity_levels", []))
    ids: list[str] = []
    for e in data.get("entries", []):
        eid = e.get("id", "?")
        ids.append(eid)
        for field in REQUIRED_FIELDS:
            if field not in e:
                errors.append(f"{eid}: missing required field {field!r}")
        if e.get("maturity") not in levels:
            errors.append(f"{eid}: maturity {e.get('maturity')!r} not in maturity_levels")
        code_paths = list(e.get("code", []) or [])
        for path in code_paths + list(e.get("tests", []) or []):
            if not (ROOT / path).exists():
                errors.append(f"{eid}: referenced path does not exist: {path}")
        # Citation binding: when the entry claims an in-code citation, the
        # anchor (author surname / arXiv id) must actually appear in one of the
        # cited code files. This makes the research->code citation drift-proof.
        if e.get("in_code_citation"):
            anchor = e.get("citation_anchor")
            if not anchor:
                errors.append(f"{eid}: in_code_citation is true but citation_anchor is missing")
            else:
                found = False
                for path in code_paths:
                    p = ROOT / path
                    if p.exists() and anchor in p.read_text(encoding="utf-8", errors="ignore"):
                        found = True
                        break
                if not found:
                    errors.append(
                        f"{eid}: citation_anchor {anchor!r} not found in any code "
                        f"file — citation and code have drifted apart"
                    )
        elif e.get("citation_anchor"):
            errors.append(f"{eid}: citation_anchor set but in_code_citation is false")
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"duplicate entry id: {dup}")
    errors.extend(_validate_landscape(data))
    return errors


def _validate_landscape(data: dict) -> list[str]:
    """Check the compendium crosswalk. Ref ids must be well-formed, and every id
    (per-line compendium_refs + landscape representative_refs) must actually
    appear in the local compendium — but ONLY when that gitignored file is
    present. In CI, where it is absent, this validation is skipped so the matrix
    never hard-depends on an unpublished document."""
    errors: list[str] = []

    def _check_ids(refs, where: str) -> None:
        for r in refs or []:
            if not isinstance(r, str) or not _REF_RE.fullmatch(r):
                errors.append(f"{where}: malformed compendium ref {r!r}")

    all_refs: set[str] = set()
    for e in data.get("entries", []):
        refs = e.get("compendium_refs")
        if refs is not None and not isinstance(refs, list):
            errors.append(f"{e.get('id')}: compendium_refs must be a list")
            continue
        _check_ids(refs, f"{e.get('id')} compendium_refs")
        all_refs.update(refs or [])

    landscape = data.get("landscape") or {}
    for i, area in enumerate(landscape.get("not_implemented", []) or []):
        for field in ("theme", "compendium_chapter", "reason"):
            if not area.get(field):
                errors.append(f"landscape.not_implemented[{i}]: missing {field!r}")
        _check_ids(area.get("representative_refs"), f"landscape.not_implemented[{i}]")
        all_refs.update(area.get("representative_refs") or [])

    if COMPENDIUM.exists():
        text = COMPENDIUM.read_text(encoding="utf-8", errors="ignore")
        for r in sorted(all_refs):
            if r not in text:
                errors.append(
                    f"compendium ref {r!r} not found in {COMPENDIUM.name} — the "
                    f"crosswalk has drifted from the local landscape"
                )
    return errors


def _rel(path: str) -> str:
    """Link target for a repo-root-relative path, from the generated file's
    location (docs/research/). Paths are validated to exist, so the link always
    resolves."""
    return "../../" + path


def _code_link(path: str) -> str:
    return f"[`{path}`]({_rel(path)})"


def _lit_link(section: str) -> str:
    """Render 'docs/09-related-work.md §9' with the doc path linked."""
    parts = section.split(" ", 1)
    path, rest = parts[0], (parts[1] if len(parts) > 1 else "")
    if path.startswith("docs/") and (ROOT / path).exists():
        linked = f"[{path}]({_rel(path)})"
        return f"{linked} {rest}".rstrip()
    return section


def _reverse_indexes(entries: list[dict]) -> list[str]:
    """Bidirectional lookups: start from a code file, a control, or a claim and
    find the research line(s) that justify it. Derived entirely from the
    register, so these tables cannot drift from the forward mapping above."""
    lines: list[str] = []

    # Code file -> research lines
    code_to_res: dict[str, list[str]] = {}
    for e in entries:
        for p in e.get("code", []) or []:
            code_to_res.setdefault(p, []).append(e["id"])
    lines.append("## Reverse index: code → research")
    lines.append("")
    lines.append("| Code file | Research line(s) |")
    lines.append("|-----------|------------------|")
    for p in sorted(code_to_res):
        res = ", ".join(sorted(set(code_to_res[p])))
        lines.append(f"| {_code_link(p)} | {res} |")
    lines.append("")

    # Control -> research lines (+ code)
    control_to: dict[str, tuple[set[str], set[str]]] = {}
    for e in entries:
        for c in e.get("controls", []) or []:
            res, code = control_to.setdefault(c, (set(), set()))
            res.add(e["id"])
            code.update(e.get("code", []) or [])
    lines.append("## Reverse index: control → research → code")
    lines.append("")
    lines.append("| Control | Research line(s) | Code |")
    lines.append("|---------|------------------|------|")
    for c in sorted(control_to):
        res, code = control_to[c]
        res_s = ", ".join(sorted(res))
        code_s = ", ".join(_code_link(p) for p in sorted(code))
        lines.append(f"| `{c}` | {res_s} | {code_s} |")
    lines.append("")

    # Claim -> research lines (claims referenced in the evidence text)
    claim_to_res: dict[str, list[str]] = {}
    for e in entries:
        for cid in sorted(set(re.findall(r"CLAIM-\d+", e.get("evidence", "") or ""))):
            claim_to_res.setdefault(cid, []).append(e["id"])
    if claim_to_res:
        lines.append("## Reverse index: claim → research")
        lines.append("")
        lines.append(
            "Claims named in a research line's evidence. Not every line cites a "
            "claim id in prose; absence here does not mean absence of evidence "
            "(see each line's **Evidence** field above)."
        )
        lines.append("")
        lines.append("| Claim | Research line(s) |")
        lines.append("|-------|------------------|")
        for cid in sorted(claim_to_res):
            res = ", ".join(sorted(set(claim_to_res[cid])))
            lines.append(f"| {cid} | {res} |")
        lines.append("")

    return lines


def _landscape_line(e: dict) -> str:
    """One-line landscape anchor for an entry: its compendium refs, else the
    honest note about why the line has no anchor in the local landscape."""
    refs = e.get("compendium_refs") or []
    if refs:
        rendered = ", ".join(f"`{r}`" for r in refs)
        note = e.get("compendium_note")
        return f"{rendered}" + (f" — {note}" if note else "")
    note = e.get("compendium_note")
    return note or "— (not anchored in the local landscape)"


def _landscape_coverage(data: dict) -> list[str]:
    """Appendix: compendium work -> research line (reverse crosswalk) and the
    areas of the landscape REMORA deliberately does not implement."""
    landscape = data.get("landscape") or {}
    lines: list[str] = []
    lines.append("## Research landscape coverage")
    lines.append("")
    lines.append(
        "Crosswalk to the broader AI-assurance landscape "
        f"(`{landscape.get('source', '—')}`). "
        f"{landscape.get('source_status', '')} These are reference pointers, "
        "**not** implementation claims — a work appearing here means it informs a "
        "line, not that REMORA implements it."
    )
    lines.append("")

    ref_to_res: dict[str, list[str]] = {}
    for e in data["entries"]:
        for r in e.get("compendium_refs") or []:
            ref_to_res.setdefault(r, []).append(e["id"])
    if ref_to_res:
        lines.append("### Compendium work → REMORA research line")
        lines.append("")
        lines.append("| Compendium id | Research line(s) |")
        lines.append("|---------------|------------------|")
        for r in sorted(ref_to_res):
            lines.append(f"| `{r}` | {', '.join(sorted(set(ref_to_res[r])))} |")
        lines.append("")

    not_impl = landscape.get("not_implemented") or []
    if not_impl:
        lines.append("### Deliberately not implemented (scope boundaries)")
        lines.append("")
        lines.append(
            "Whole areas of the landscape REMORA does not implement as controls, "
            "recorded so the boundary is explicit and auditable rather than an "
            "unstated gap. These are boundaries, not roadmap promises."
        )
        lines.append("")
        lines.append("| Area | Compendium chapter | Representative works | Why REMORA does not implement it |")
        lines.append("|------|--------------------|----------------------|----------------------------------|")
        for a in not_impl:
            reps = ", ".join(f"`{r}`" for r in a.get("representative_refs", []) or []) or "—"
            lines.append(
                f"| {a.get('theme', '—')} | {a.get('compendium_chapter', '—')} | "
                f"{reps} | {a.get('reason', '—')} |"
            )
        lines.append("")
    return lines


def render(data: dict) -> str:
    lines: list[str] = []
    lines.append("<!-- GENERATED FILE — DO NOT EDIT.")
    lines.append("     Source: docs/research/research_control_matrix_v1.yaml")
    lines.append("     Regenerate: python scripts/generate_research_control_matrix.py -->")
    lines.append("")
    lines.append("# REMORA Research Control Matrix")
    lines.append("")
    lines.append(
        "The machine-checked chain from research source to tested code, one row "
        "per research line. Every code and test path below is verified to exist "
        "on disk by CI; the literature narrative lives in "
        "[docs/09-related-work.md](../09-related-work.md)."
    )
    lines.append("")
    lines.append(
        f"Source of truth: `docs/research/research_control_matrix_v1.yaml` "
        f"(schema {data.get('schema_version')}, updated {data.get('updated')})."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| ID | Research line | Controls | Maturity |")
    lines.append("|----|---------------|----------|----------|")
    for e in data["entries"]:
        controls = ", ".join(f"`{c}`" for c in e["controls"])
        lines.append(
            f"| {e['id']} | {e['title']} | {controls} | `{e['maturity']}` |"
        )
    lines.append("")
    for e in data["entries"]:
        lines.append(f"## {e['id']} — {e['title']}")
        lines.append("")
        if e.get("in_code_citation"):
            cite_note = f" (cited in code; anchor `{e['citation_anchor']}` — CI-verified)"
        else:
            cite_note = " (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)"
        lines.append(f"- **Source:** {e['source']['citation']}{cite_note}")
        for s in e["source"].get("sections", []) or []:
            lines.append(f"  - {s}")
        for b in e["source"].get("builds_on", []) or []:
            lines.append(f"  - builds on: {b}")
        lines.append(f"- **Concepts:** {', '.join(e['concepts'])}")
        lines.append(f"- **REMORA controls:** {', '.join(e['controls'])}")
        lines.append("- **Code:** " + ", ".join(_code_link(p) for p in e["code"]))
        tests = e.get("tests") or []
        lines.append(
            "- **Tests:** "
            + (", ".join(_code_link(p) for p in tests) if tests else "—")
        )
        lines.append(f"- **Evidence:** {e['evidence']}")
        lines.append(f"- **Maturity:** `{e['maturity']}`")
        lines.append(f"- **Scope boundary:** {e['scope_boundary']}")
        lines.append(f"- **Literature:** {_lit_link(e['related_work_section'])}")
        lines.append(f"- **Landscape (local compendium):** {_landscape_line(e)}")
        lines.append("")
    lines.extend(_reverse_indexes(data["entries"]))
    lines.extend(_landscape_coverage(data))
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    data = _load()
    errors = validate(data)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    rendered = render(data)
    if check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print(
                "ERROR: docs/research/research_control_matrix.generated.md is "
                "stale — run: python scripts/generate_research_control_matrix.py",
                file=sys.stderr,
            )
            return 1
        print("research control matrix: up to date")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(data['entries'])} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
