# Author: Stian Skogbrott
# License: Apache-2.0
"""Add PVD subsection to paper (tex and md)."""

# =====================================================================
# TEX
# =====================================================================
with open('paper/remora_paper.tex', encoding='utf-8') as f:
    tex = f.read()

pvd_tex = r"""
\subsection{Prover-Verifier Deliberation for Critical-Phase Routing}
\label{sec:pvd}

Kirsch et al.\ (2024) showed that prover-verifier games produce more
legible and reliable LLM outputs: a \emph{prover} oracle justifies a
claim to an independent \emph{verifier} oracle, filtering responses
whose reasoning cannot withstand scrutiny \cite{kirsch2024prover}.
REMORA adapts this protocol to its offline multi-oracle setting without
additional API calls.

\paragraph{Protocol.}
\begin{enumerate}[leftmargin=*,label=\arabic*.]
  \item \textbf{Cluster} oracle responses via Semantic Entropy clustering
        (\S\ref{sec:se}), producing semantic equivalence classes
        $\mathcal{C} = \{C_1, \ldots, C_K\}$ sorted by mass.
  \item \textbf{Prover} = the oracle whose response belongs to the
        dominant cluster $C_1$ and has the highest per-oracle confidence.
  \item \textbf{Verifier} = the oracle with the highest confidence
        \emph{outside} $C_1$ (the independent challenger).
  \item \textbf{Deliberation} ($r = 1, \ldots, n_{\text{rounds}}$):
        evaluate bidirectional NLI entailment
        $e_r = \text{NLI}(\text{prover} \to \text{verifier}) \cdot \gamma^{r-1}$
        with round-decay factor $\gamma = 0.85$.
  \item \textbf{Legibility score}:
        $\mathcal{L} = \bar{e} \cdot |C_1| / N$,
        where $\bar{e}$ is the mean entailment and $|C_1|/N$ is the
        dominant cluster mass.
  \item \textbf{Final confidence}:
        $\hat{c} = \sqrt{|C_1|/N \cdot c_{\text{verifier}}}$
        (geometric mean of prover support and updated verifier confidence).
\end{enumerate}

\paragraph{Routing signal.}
The PVD confidence is blended with the raw REMORA trust score:
\begin{equation}
  \tilde{\tau} = (1 - w_{\text{pvd}}) \cdot \tau + w_{\text{pvd}} \cdot \hat{c},
  \qquad w_{\text{pvd}} = 0.40
  \label{eq:pvd_blend}
\end{equation}
This allows PVD to promote borderline critical-phase items to
\textsc{Accept} when deliberation confidence is high, extending coverage
beyond the \texttt{PhaseAwareGuardrail} operating point without
relaxing the formal risk bound.

\paragraph{Implementation.}
\texttt{remora.selective.pvd.deliberate(oracle\_responses, oracle\_confidences,
n\_rounds=2)} returns a \texttt{PVDResult} with fields
\texttt{prover\_cluster\_mass}, \texttt{legibility\_score},
\texttt{agreement}, and \texttt{final\_confidence}.
\texttt{pvd\_routing\_score(trust\_score, pvd\_result)} implements
Eq.~\ref{eq:pvd_blend}.  Fully tested (33 unit tests, no external
model calls).

"""

# Insert before CriticalEvidenceRouter subsection
router_marker = r'\subsection{CriticalEvidenceRouter}'
assert router_marker in tex, "CriticalEvidenceRouter marker not found"
tex = tex.replace(router_marker, pvd_tex + router_marker)

# Update related-work section: add PVD reference
old_rw = (
    r'\subsection{AI Governance and Policy-as-Code}'
)
new_rw_prefix = (
    r"""\subsection{Prover-Verifier Games}
Kirsch et al.\ (2024) \cite{kirsch2024prover} showed that prover-verifier
games improve LLM output legibility by requiring the prover to justify
claims to an independent verifier.  REMORA adapts this to the offline
multi-oracle case, using Semantic Entropy clustering to identify the prover
(dominant-cluster oracle) and verifier (independent challenger) without
additional API calls (\S\ref{sec:pvd}).

"""
)
tex = tex.replace(old_rw, new_rw_prefix + old_rw)

with open('paper/remora_paper.tex', 'w', encoding='utf-8') as f:
    f.write(tex)
print("TEX: OK")

# =====================================================================
# MARKDOWN
# =====================================================================
with open('paper/remora_paper.md', encoding='utf-8') as f:
    md = f.read()

pvd_md = """
### 7.3 Prover-Verifier Deliberation for Critical-Phase Routing

Kirsch et al. (2024) showed that prover-verifier games produce more legible and reliable LLM outputs. REMORA adapts this protocol to its offline multi-oracle setting without additional API calls.

**Protocol:**
1. **Cluster** oracle responses via Semantic Entropy clustering, producing semantic equivalence classes sorted by mass.
2. **Prover** = the oracle from the dominant cluster with highest confidence.
3. **Verifier** = the highest-confidence oracle *outside* the dominant cluster.
4. **Deliberation** (r = 1, ..., n_rounds): evaluate NLI entailment score prover→verifier with round-decay γ=0.85.
5. **Legibility score**: L = mean_entailment × cluster_mass.
6. **Final confidence**: geometric mean of dominant cluster mass and updated verifier confidence.

**Routing signal:** PVD confidence blended with REMORA trust score:

$$\\tilde{\\tau} = (1 - w_{\\text{pvd}}) \\cdot \\tau + w_{\\text{pvd}} \\cdot \\hat{c}, \\quad w_{\\text{pvd}} = 0.40$$

Implementation: `remora.selective.pvd.deliberate(oracle_responses, oracle_confidences, n_rounds=2)` returns a `PVDResult`. `pvd_routing_score(trust_score, pvd_result)` implements the blending. Tested: 33 unit tests, no external model calls.

"""

# Insert before section 7.4 (was 7.3 before CRC was added as 7.2)
marker_74 = "### 7.4 Evidence Router Design"
marker_73_alt = "### 7.3 Evidence Router Design"
if marker_74 in md:
    md = md.replace(marker_74, pvd_md + marker_74)
    print("MD PVD (7.4 marker): OK")
elif marker_73_alt in md:
    # Renumber 7.3 -> 7.4
    md = md.replace(marker_73_alt, "### 7.4 Evidence Router Design")
    md = md.replace("### 7.4 Evidence Router Design", pvd_md + "### 7.4 Evidence Router Design")
    print("MD PVD (7.3 -> 7.4 renumber): OK")
else:
    print("WARNING: Evidence Router marker not found in MD")

with open('paper/remora_paper.md', 'w', encoding='utf-8') as f:
    f.write(md)
print("MD: OK")
print("Done")
