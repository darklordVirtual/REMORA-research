# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Citation parity between paper/remora_paper.md and paper/remora_paper.tex.

Guards the tex-lockstep finding from the 2026-08-05 external review: the PDF
compiles from the .tex, so a reference present only in the .md ships a PDF
with a thinner bibliography than the claim gates reviewed. The real-file test
fails CI on any future one-sided reference edit; the synthetic tests pin the
detector's failure modes so it cannot silently go blind.
"""
from __future__ import annotations

from scripts.check_paper_sync import (
    MD,
    TEX,
    _citation_parity_errors,
    _first_surname,
    _md_references,
    _normalize,
    _tex_bib_entries,
)

MD_TEXT = MD.read_text(encoding="utf-8", errors="replace")
TEX_TEXT = TEX.read_text(encoding="utf-8", errors="replace")


def test_real_paper_has_citation_parity() -> None:
    errors = _citation_parity_errors(MD_TEXT, TEX_TEXT)
    assert errors == [], "\n".join(errors)


def test_real_paper_reference_counts_match() -> None:
    refs, _ = _md_references(MD_TEXT)
    entries = _tex_bib_entries(TEX_TEXT)
    assert len(refs) == len(entries), (
        f"{len(refs)} .md references vs {len(entries)} .tex bibitems"
    )
    assert len(refs) >= 60  # the post-review reference set; guards mass deletion


def _mini_md(refs: list[str], body: str) -> str:
    bullets = "\n\n".join(f"- {r}" for r in refs)
    return f"# Paper\n\n{body}\n\n## References\n\n{bullets}\n\n## Appendix A\n"


_MINI_TEX = r"""
Kuhn et al.\ \cite{kuhn2023semantic} propose semantic entropy.
\begin{thebibliography}{9}
\bibitem{kuhn2023semantic}
Kuhn, L., Gal, Y., \& Farquhar, S.\ (2023).
Semantic uncertainty.
\end{thebibliography}
"""


def test_synthetic_parity_ok() -> None:
    md = _mini_md(
        ["Kuhn, L., Gal, Y., & Farquhar, S. (2023). Semantic uncertainty."],
        "Kuhn et al. (2023) propose semantic entropy.",
    )
    assert _citation_parity_errors(md, _MINI_TEX) == []


def test_md_only_reference_is_detected() -> None:
    md = _mini_md(
        [
            "Kuhn, L., Gal, Y., & Farquhar, S. (2023). Semantic uncertainty.",
            "Ville, J. (1939). Étude critique de la notion de collectif.",
        ],
        "Kuhn et al. (2023) and Ville (1939) are discussed.",
    )
    errors = _citation_parity_errors(md, _MINI_TEX)
    assert any("Ville" in e and "no bibitem" in e for e in errors)


def test_uncited_md_reference_is_detected() -> None:
    md = _mini_md(
        ["Kuhn, L., Gal, Y., & Farquhar, S. (2023). Semantic uncertainty."],
        "This body never names the reference.",
    )
    errors = _citation_parity_errors(md, _MINI_TEX)
    assert any("never cited in the paper text" in e for e in errors)


def test_tex_only_bibitem_is_detected() -> None:
    md = _mini_md(
        ["Kuhn, L., Gal, Y., & Farquhar, S. (2023). Semantic uncertainty."],
        "Kuhn et al. (2023) propose semantic entropy.",
    )
    tex = _MINI_TEX.replace(
        r"\end{thebibliography}",
        "\\bibitem{ghost2020}\nGhost, G.\\ (2020).\nUnmatched work.\n"
        r"\end{thebibliography}",
    )
    errors = _citation_parity_errors(md, tex)
    assert any("ghost2020" in e for e in errors)
    # the ghost bibitem is also never \cite-d
    assert any("never \\cite-d" in e for e in errors)


def test_dangling_cite_key_is_detected() -> None:
    md = _mini_md(
        ["Kuhn, L., Gal, Y., & Farquhar, S. (2023). Semantic uncertainty."],
        "Kuhn et al. (2023) propose semantic entropy.",
    )
    tex = _MINI_TEX.replace(
        r"\cite{kuhn2023semantic}", r"\cite{kuhn2023semantic,missing2024}"
    )
    errors = _citation_parity_errors(md, tex)
    assert any("missing2024" in e and "no bibitem" in e for e in errors)


def test_normalize_handles_latex_accents_and_unicode() -> None:
    assert _normalize(r"Gr\"unwald") == "Grunwald"
    assert _normalize("Grünwald") == "Grunwald"
    assert _normalize(r"Cand\`es") == "Candes"
    assert _normalize(r"Howard, S.~R.") == "Howard, S. R."


def test_first_surname_extraction() -> None:
    assert _first_surname("El-Yaniv, R. & Wiener, Y. (2010).") == "El-Yaniv"
    assert _first_surname("European Parliament & Council. (2024).") == "European"
    assert _first_surname("Bjøru, A. R. (2026). Causal Post-hoc XAI.") == "Bjøru"
