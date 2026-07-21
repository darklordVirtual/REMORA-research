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

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "research" / "research_control_matrix_v1.yaml"
OUTPUT = ROOT / "docs" / "research" / "research_control_matrix.generated.md"

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
    import re as _re

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
        for cid in sorted(set(_re.findall(r"CLAIM-\d+", e.get("evidence", "") or ""))):
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
        lines.append("")
    lines.extend(_reverse_indexes(data["entries"]))
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
