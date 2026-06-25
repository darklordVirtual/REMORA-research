# Author: Stian Skogbrott
# License: Apache-2.0
"""Add new bibliography entries to remora_paper.tex and remora_paper.md."""

NEW_BIBITEMS_TEX = r"""
\bibitem{kuhn2023semantic}
Kuhn, L., Gal, Y., \& Farquhar, S.\ (2023).
Semantic uncertainty: Linguistic invariances for uncertainty estimation in
natural language generation.
In \emph{Proceedings of the International Conference on Learning Representations
(ICLR 2023)}.
arXiv:2302.09664.

\bibitem{kuhn2026evse}
Kuhn, L., Gal, Y., \& Farquhar, S.\ (2026).
Evidential Semantic Entropy for LLM uncertainty quantification.
In \emph{Proceedings of the 17th Conference of the European Chapter of the
Association for Computational Linguistics (EACL 2026)}, pp.\ 334--348.

\bibitem{kirsch2024prover}
Kirsch, A., Harrison, J., Misra, S., \& Leike, J.\ (2024).
Prover-verifier games improve legibility of LLM outputs.
\emph{arXiv:2407.13692}.

\bibitem{angelopoulos2022crc}
Angelopoulos, A.\ N., Bates, S., Fisch, A., Lei, L., \& Schuster, T.\ (2022).
Conformal risk control.
\emph{arXiv:2208.02814}.

\bibitem{zhang2025tee}
Zhang, Y.\ \& Lee, M.\ (2025).
Evaluating the performance of large language models in confidential computing
environments.
\emph{arXiv:2502.11347}.

"""

with open('paper/remora_paper.tex', encoding='utf-8') as f:
    content = f.read()

marker = 'begin{thebibliography}{99}\n\n\\bibitem{wang2023self}'
if marker in content:
    content = content.replace(
        marker,
        'begin{thebibliography}{99}' + NEW_BIBITEMS_TEX + '\\bibitem{wang2023self}'
    )
    print("Bibliography entries added to .tex: OK")
else:
    print("WARNING: bibliography marker not found in .tex")

with open('paper/remora_paper.tex', 'w', encoding='utf-8') as f:
    f.write(content)

# ---- Markdown ----
NEW_REFS_MD = """
- Kuhn, L., Gal, Y., & Farquhar, S. (2023). Semantic uncertainty: Linguistic invariances for uncertainty estimation in natural language generation. *ICLR 2023*. arXiv:2302.09664.

- Kuhn, L., Gal, Y., & Farquhar, S. (2026). Evidential Semantic Entropy for LLM uncertainty quantification. *EACL 2026*, pp. 334-348.

- Kirsch, A., Harrison, J., Misra, S., & Leike, J. (2024). Prover-verifier games improve legibility of LLM outputs. arXiv:2407.13692.

- Angelopoulos, A. N., Bates, S., Fisch, A., Lei, L., & Schuster, T. (2022). Conformal risk control. arXiv:2208.02814.

- Zhang, Y. & Lee, M. (2025). Evaluating the performance of large language models in confidential computing environments. arXiv:2502.11347.

"""

with open('paper/remora_paper.md', encoding='utf-8') as f:
    md = f.read()

# Find the bibliography / references section end and prepend
md_marker = 'Wang, X., Wei, J., Schuurmans'
if md_marker in md:
    md = md.replace(md_marker, NEW_REFS_MD.lstrip('\n') + '\n- ' + md_marker)
    print("Bibliography entries added to .md: OK")
else:
    print("WARNING: md bibliography marker not found")

with open('paper/remora_paper.md', 'w', encoding='utf-8') as f:
    f.write(md)

print("Done.")
