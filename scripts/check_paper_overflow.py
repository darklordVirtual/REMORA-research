# Author: Stian Skogbrott
# License: Apache-2.0
"""Geometric overflow guard for the two-column paper PDF.

Flags words that protrude into the page margin or cross the inter-column
gutter — the two failure modes of twocolumn LaTeX (overwide tables,
unbreakable tokens, verbatim blocks). Run by CI after every compile so
layout regressions fail the build instead of shipping.

Letter paper: 612pt wide, 1in margins -> text block x in [72, 540].
Two columns, 10pt columnsep -> gutter starts at ~306pt.

Usage: python scripts/check_paper_overflow.py [pdf_path]
Exit codes: 0 = clean, 1 = overflow detected.
"""
from __future__ import annotations

import sys

import fitz  # PyMuPDF

PDF_DEFAULT = "paper/remora_paper.pdf"
PAGE_RIGHT_EDGE = 540.0
MARGIN_SLACK = 3.0
GUTTER_START = 540 - (540 - 72 - 10) / 2  # ~306
GUTTER_SLACK = 8.0
TITLE_BLOCK_Y = 280.0  # page-1 title/author block legitimately spans both columns


def main() -> int:
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else PDF_DEFAULT
    sys.stdout.reconfigure(errors="replace")
    doc = fitz.open(pdf_path)
    issues = 0
    for pno, page in enumerate(doc, 1):
        for x0, y0, x1, _y1, word, *_ in page.get_text("words"):
            if pno == 1 and y0 < TITLE_BLOCK_Y:
                continue
            if x1 > PAGE_RIGHT_EDGE + MARGIN_SLACK:
                print(f"p{pno:2} MARGIN  x1={x1:6.1f} y={y0:6.1f} {word[:40]!r}")
                issues += 1
            elif x0 < GUTTER_START - GUTTER_SLACK and x1 > GUTTER_START + GUTTER_SLACK:
                print(f"p{pno:2} GUTTER  x0={x0:6.1f} x1={x1:6.1f} y={y0:6.1f} {word[:40]!r}")
                issues += 1
    print(f"pages={len(doc)} flagged_words={issues}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
