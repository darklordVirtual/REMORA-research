#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Keep the three paper artifacts coherent: remora_paper.md, .tex and the PDF.

The PDF compiles from remora_paper.tex, but the claim gates track
remora_paper.md, so the two hand-maintained sources used to drift silently —
the .tex shipped a stale "no tool dispatch" execution claim and a frozen
"content dated June 2026" stamp while the .md tracked the wired dispatcher.
This gate makes .md the single version authority and fails CI when the .tex
(and therefore the PDF) diverges from it.

Checks (all hard):
1. VERSION AUTHORITY — the version + revision-date strings in the .md title
   line must appear verbatim in the .tex \\paperversion macro. One edit in the
   .md, mirrored in the .tex; the gate proves both (and the compiled PDF)
   agree.
2. NO STALE PROCESS CLAIMS — a blacklist of superseded phrases must appear in
   NEITHER file (e.g. "no tool dispatch", which the wired GovernedToolDispatcher
   contradicts).
3. REQUIRED ANCHORS — load-bearing framing that must be present in BOTH files
   (SHADOW_ONLY posture; the GovernedToolDispatcher execution path).
4. CITATION PARITY — the .md "## References" list and the .tex bibliography
   must describe the same set of works (matched on first-author surname +
   year, both directions), every .tex bibitem must be \\cite-d somewhere,
   every \\cite key must have a bibitem, and every .md reference must be
   cited somewhere in the .md text. Added 2026-08-07 after the .tex shipped
   27 bibitems against 60 .md references (external review, tex-lockstep
   finding).

Stdlib only (the documentation-governance CI job ships no third-party deps).
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "paper" / "remora_paper.md"
TEX = ROOT / "paper" / "remora_paper.tex"

# Superseded phrases that must not reappear in either source.
STALE_PHRASES = (
    ("no tool dispatch",
     "the execution path dispatches via GovernedToolDispatcher (CAP-013, 2026-07-27)"),
    ("dispatcher not wired",
     "the dispatcher is wired into /v1/execution/execute since 2026-07-27"),
    ("does NOT invoke tools",
     "the PEP dispatches the tool under an ExecutionLease"),
    ("content dated June 2026",
     "the paper carries a live revision date, not a frozen June-2026 stamp"),
    ("unchanged content",
     "the .tex is kept in lockstep with the code, not declared unchanged"),
)

# Anchors that must appear in BOTH files (case-sensitive substring).
REQUIRED_IN_BOTH = (
    "SHADOW_ONLY",
    "GovernedToolDispatcher",
)

# Authoritative version stamp lives in the .md title block.
_MD_VERSION_RE = re.compile(
    r"Paper version\s+(v\d+\.\d+\.\d+)\s*.\s*revision\s+(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)


# ── Check 4: citation parity ────────────────────────────────────────────────
# Institutional .md references whose "surname" (first word) needs a fuller
# token when searched for in running text.
_BODY_TOKEN = {
    "European": "European Parliament",
    "International": "IEC 61511",
    "Standards": "NORSOK",
    "Open": "Open Policy Agent",
}

_YEAR_RE = re.compile(r"\((19|20)\d{2}[ab]?\)")


def _normalize(text: str) -> str:
    """De-escape LaTeX and strip accents so surnames compare across sources."""
    text = text.replace("\\&", "&").replace("~", " ")
    text = re.sub(r"\\[`'\"^]", "", text)  # accent macros: \'E \`e \"u
    text = text.replace("\\", "").replace("{", "").replace("}", "")
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _md_references(md: str) -> tuple[list[str], str]:
    """Return (reference bullets, md text with the References block removed)."""
    lines = md.split("\n")
    try:
        start = next(i for i, line in enumerate(lines)
                     if line.strip() == "## References")
        end = next(i for i in range(start + 1, len(lines))
                   if lines[i].startswith("## "))
    except StopIteration:
        return [], md
    refs = [ln[2:].strip() for ln in lines[start:end] if ln.startswith("- ")]
    rest = "\n".join(lines[:start] + lines[end:])
    return refs, rest


def _first_surname(ref: str) -> str:
    norm = _normalize(ref)
    m = re.match(r"([\w'-]+)[,. ]", norm)
    return m.group(1) if m else norm.split()[0].rstrip(",.")


def _tex_bib_entries(tex: str) -> list[tuple[str, str]]:
    try:
        block = tex[tex.index(r"\begin{thebibliography}"):
                    tex.index(r"\end{thebibliography}")]
    except ValueError:
        return []
    parts = re.split(r"\\bibitem\{([^}]+)\}", block)
    # parts = [preamble, key1, body1, key2, body2, ...]
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def _citation_parity_errors(md: str, tex: str) -> list[str]:
    errors: list[str] = []
    refs, md_rest = _md_references(md)
    entries = _tex_bib_entries(tex)
    if not refs:
        return [f"{MD.name}: no '## References' bullet list found"]
    if not entries:
        return [f"{TEX.name}: no thebibliography block found"]

    norm_entries = [(key, _normalize(body)) for key, body in entries]
    norm_refs_text = _normalize(" ".join(refs))
    norm_md_rest = _normalize(md_rest)

    for ref in refs:
        surname = _first_surname(ref)
        year_m = _YEAR_RE.search(ref)
        year = year_m.group(0)[1:5] if year_m else None
        hit = any(
            re.search(rf"\b{re.escape(surname)}\b", body)
            and (year is None or f"({year}" in body)
            for _, body in norm_entries
        )
        if not hit:
            errors.append(
                f"{TEX.name}: no bibitem matches .md reference "
                f"'{ref[:60]}...' (surname {surname!r}, year {year})")
        body_token = _BODY_TOKEN.get(surname, surname)
        if not re.search(re.escape(body_token), norm_md_rest):
            errors.append(
                f"{MD.name}: reference '{ref[:60]}...' is never cited in "
                f"the paper text (searched for {body_token!r})")

    for key, body in norm_entries:
        first = re.match(r"\s*([\w'-]+)", body)
        token = first.group(1) if first else key
        if not re.search(rf"\b{re.escape(token)}\b", norm_refs_text):
            errors.append(
                f"{MD.name}: no .md reference matches bibitem {key!r} "
                f"(first author token {token!r})")

    cited: set[str] = set()
    for group in re.findall(r"\\cite\{([^}]+)\}", tex):
        cited.update(k.strip() for k in group.split(","))
    keys = {key for key, _ in entries}
    for key, _ in entries:
        if key not in cited:
            errors.append(f"{TEX.name}: bibitem {key!r} is never \\cite-d")
    for key in sorted(cited - keys):
        errors.append(f"{TEX.name}: \\cite key {key!r} has no bibitem")
    return errors


def main() -> int:
    md = MD.read_text(encoding="utf-8", errors="replace")
    tex = TEX.read_text(encoding="utf-8", errors="replace")
    # De-escape LaTeX underscores so anchors like SHADOW_ONLY match the .tex's
    # SHADOW\_ONLY form.
    md_norm = md.replace("\\_", "_")
    tex_norm = tex.replace("\\_", "_")
    errors = 0

    # 1. Version authority.
    m = _MD_VERSION_RE.search(md)
    if not m:
        _fail(f"{MD.name}: could not find the authoritative "
              "'Paper version vX.Y.Z · revision YYYY-MM-DD' line")
        errors += 1
    else:
        version, revision = m.group(1), m.group(2)
        if version not in tex:
            _fail(f"{TEX.name}: version {version!r} (authority: {MD.name}) not found in "
                  r"\paperversion — the PDF would ship a different version")
            errors += 1
        if revision not in tex:
            _fail(f"{TEX.name}: revision date {revision!r} (authority: {MD.name}) not found "
                  "— .tex/.pdf and .md disagree on the revision")
            errors += 1
        if not errors:
            print(f"[OK]   version + revision in lockstep: {version} / {revision}")

    # 2. No stale process claims in either source.
    for path, text in ((MD, md), (TEX, tex)):
        for phrase, why in STALE_PHRASES:
            if phrase in text:
                _fail(f"{path.name}: stale phrase {phrase!r} present — {why}")
                errors += 1

    # 3. Required anchors in both (LaTeX underscore-escaping normalized).
    for anchor in REQUIRED_IN_BOTH:
        for path, text in ((MD, md_norm), (TEX, tex_norm)):
            if anchor not in text:
                _fail(f"{path.name}: required anchor {anchor!r} missing")
                errors += 1

    # 4. Citation parity between the .md reference list and the .tex bib.
    parity_errors = _citation_parity_errors(md, tex)
    for msg in parity_errors:
        _fail(msg)
    errors += len(parity_errors)
    if not parity_errors:
        n_refs = len(_md_references(md)[0])
        print(f"[OK]   citation parity: {n_refs} .md references <-> "
              f"{len(_tex_bib_entries(tex))} .tex bibitems, all cited")

    if errors:
        print(f"\n[FAIL] paper sync: {errors} issue(s) — remora_paper.md, .tex and the "
              "compiled PDF are not coherent.", file=sys.stderr)
        return 1
    print("[PASS] paper sync: .md, .tex and PDF version/claims are coherent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
