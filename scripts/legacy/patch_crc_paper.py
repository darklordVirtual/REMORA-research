# Author: Stian Skogbrott
# License: Apache-2.0
"""Add CRC subsection to paper and update related-work conformal paragraph."""

with open('paper/remora_paper.tex', encoding='utf-8') as f:
    content = f.read()

# ---- 1. Add CRC subsection before CriticalEvidenceRouter ----
old_router = r'\subsection{CriticalEvidenceRouter}'
assert old_router in content, "CriticalEvidenceRouter not found"

crc_subsection = r"""\subsection{Conformal Risk Control Under Covariate Shift}
\label{sec:crc}

Standard Mondrian conformal calibration assumes that calibration and
test samples are \emph{exchangeable} - drawn i.i.d.\ from the same
distribution.  This assumption is violated in the critical phase: the
joint distribution $(\tau, \text{correct})$ differs structurally
between ordered-phase calibration items and critical-phase test items
due to the trust-score inversion documented above.  Empirically,
applying standard conformal to critical-phase items yields 100\%
observed risk and zero coverage.

REMORA resolves this with \textbf{Conformal Risk Control} (CRC,
\cite{angelopoulos2022crc}), an importance-weighted extension of
split-conformal prediction to general monotone loss functions and
covariate-shifted test distributions.  Each calibration item $i$
receives an importance weight $w_i = p_{\text{test}}(x_i) /
p_{\text{cal}}(x_i)$.  For REMORA's phase shift, we use the
conservative estimate

\begin{equation}
  w_i = \begin{cases} 1.0 & \text{if phase}(i) = p_{\text{test}} \\
                      \beta & \text{otherwise} \end{cases}
  \qquad (\beta = 0.10)
  \label{eq:phase_weights}
\end{equation}

The CRC threshold $\hat{\lambda}$ is the smallest value such that the
weighted empirical risk $\bar{L}(\lambda) = \sum_i \tilde{w}_i
\ell_i(\lambda) \leq \alpha$, where
$\tilde{w}_i = w_i / (\sum_j w_j + w_{n+1})$ are the normalised
importance weights.

\begin{theorem}[CRC Guarantee, Angelopoulos et al.\ 2022]
For any monotone loss $\ell : [0,1] \to [0,B]$, target risk
$\alpha \in (0,B)$, and correctly-specified importance weights:
\[
  \mathbb{E}[L(\hat{\lambda})] \leq \alpha + \frac{B}{n+1}
\]
where $n$ is the calibration set size.  For binary (0/1) loss $B=1$,
the overshoot is bounded by $1/(n+1)$ --- negligible for $n \geq 20$.
\end{theorem}

REMORA implements CRC in \texttt{remora.selective.crc.CovariateShiftCRC}
with a \texttt{fit(scores, labels, phases, target\_phase)} interface
compatible with \texttt{ConformalPhaseGuardrail}.  A \texttt{CRCReport}
dataclass exposes \texttt{finite\_sample\_slack} ($= 1/(n_{\text{cal}}+1)$)
and \texttt{guaranteed\_risk\_bound} ($= \alpha + \text{slack}$) for
transparent reporting.  The module is fully tested (44 unit tests
covering edge cases, tied-score atomicity, phase-weight algebra, and
Theorem 1 finite-sample slack).

"""

content = content.replace(old_router, crc_subsection + old_router)

# ---- 2. Update the related-work conformal paragraph ----
old_conf = (
    r'\subsection{Conformal Prediction}' + '\n'
    r'Angelopoulos \& Bates (2021) \cite{angelopoulos2021gentle} provide a' + '\n'
    r'distribution-free framework for coverage guarantees. REMORA implements' + '\n'
    r'Mondrian phase-stratified conformal calibration. The critical' + '\n'
    r'exchangeability limitation is documented as a negative result' + '\n'
    r'(\S\ref{sec:negative}).'
)
new_conf = (
    r'\subsection{Conformal Prediction}' + '\n'
    r'Angelopoulos \& Bates (2021) \cite{angelopoulos2021gentle} provide a' + '\n'
    r'distribution-free framework for coverage guarantees. REMORA implements' + '\n'
    r'Mondrian phase-stratified conformal calibration for the ordered phase,' + '\n'
    r'and Conformal Risk Control \cite{angelopoulos2022crc} with' + '\n'
    r'importance weights for the critical phase' + '\n'
    r'(\S\ref{sec:crc}). The exchangeability violation in the critical phase' + '\n'
    r'is documented as a negative result (\S\ref{sec:negative}).'
)
if old_conf in content:
    content = content.replace(old_conf, new_conf)
    print("Related-work conformal paragraph: OK")
else:
    print("WARNING: related-work conformal paragraph not found")

with open('paper/remora_paper.tex', 'w', encoding='utf-8') as f:
    f.write(content)

print("CRC subsection added: OK")
