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

Stdlib only (the documentation-governance CI job ships no third-party deps).
"""
from __future__ import annotations

import re
import sys
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

    if errors:
        print(f"\n[FAIL] paper sync: {errors} issue(s) — remora_paper.md, .tex and the "
              "compiled PDF are not coherent.", file=sys.stderr)
        return 1
    print("[PASS] paper sync: .md, .tex and PDF version/claims are coherent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
