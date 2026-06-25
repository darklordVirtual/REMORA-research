# Author: Stian Skogbrott
# License: Apache-2.0
"""Patch paper Stages 3-4 and method section for Semantic Entropy."""

with open('paper/remora_paper.tex', encoding='utf-8') as f:
    content = f.read()

# --- Stage 3 ---
old3 = (
    'Stage 3: Canonicalization \\& Weighted Consensus.}\n'
    'Each response is canonicalized by $\\varphi: \\mathrm{raw} \\rightarrow v$\n'
    'where $v$ is the tuple (\\texttt{polarity}, \\texttt{claim\\_hash},\n'
    '\\texttt{magnitude}, \\texttt{tags}),\n'
    'and \\texttt{claim\\_hash} is a 16-character SHA-256 truncation over\n'
    'NFKC-normalized sorted tokens. Oracle weights are derived from\n'
    'inverse pairwise correlation (see \\S\\ref{sec:method}).'
)
new3 = (
    'Stage 3: Canonicalization \\& Weighted Consensus.}\n'
    'Each response is canonicalized by $\\varphi: \\mathrm{raw} \\rightarrow v$\n'
    'where $v$ is the tuple (\\texttt{polarity}, \\texttt{claim\\_hash},\n'
    '\\texttt{magnitude}, \\texttt{tags}).\n'
    'The \\texttt{claim\\_hash} field uses a pluggable backend: the default\n'
    '\\texttt{TokenFingerprintBackend} applies a 16-char SHA-256 truncation over\n'
    'NFKC-normalized sorted tokens for backward-compatible, dependency-free\n'
    'operation; the \\texttt{NLISemanticBackend} replaces this with bidirectional\n'
    'cross-encoder entailment clustering, implementing Semantic Entropy\n'
    '\\cite{kuhn2023semantic}. Oracle weights are derived from\n'
    'inverse pairwise correlation (see \\S\\ref{sec:method}).'
)
if old3 in content:
    content = content.replace(old3, new3)
    print("Stage 3: OK")
else:
    print("WARNING: Stage 3 not found")

# --- Stage 4 ---
old4 = (
    'Stage 4: Thermodynamic Observables.}\n'
    'Entropy $H$, dissensus $D$, order parameter $\\eta$, structural\n'
    'temperature $T$, free-energy proxy $F$, and trust score $\\trust$ are\n'
    'computed (see \\S\\ref{sec:method}). Phase $\\in\\{\\text{ordered},\n'
    '\\text{critical}, \\text{disordered}\\}$ is assigned. Lyapunov\n'
    'observable $V(t) = H(t) + \\lambda D(t)$ is tracked.'
)
new4 = (
    'Stage 4: Thermodynamic Observables.}\n'
    'Entropy $H$ is grounded as Semantic Entropy\n'
    '$\\mathrm{SE}(x) = -\\sum_{c \\in \\mathcal{C}} p(c\\,|\\,x)\\log p(c\\,|\\,x)$\n'
    'over NLI-derived semantic equivalence clusters $\\mathcal{C}$\n'
    '\\cite{kuhn2023semantic}, replacing the token-hash heuristic.\n'
    'Dissensus $D$, order parameter $\\eta$, structural temperature $T$,\n'
    'free-energy proxy $F$, and trust score $\\trust$ are computed\n'
    '(see \\S\\ref{sec:method}). Phase $\\in\\{\\text{ordered},\n'
    '\\text{critical}, \\text{disordered}\\}$ is assigned. Lyapunov\n'
    'observable $V(t) = H(t) + \\lambda D(t)$ is tracked.'
)
if old4 in content:
    content = content.replace(old4, new4)
    print("Stage 4: OK")
else:
    print("WARNING: Stage 4 not found")

# Also update the implementation status table
old_impl = 'Canonicalization ($\\phi$) & Impl. & NFKC, claim hash \\\\'
new_impl = 'Canonicalization ($\\phi$) & Impl. & NFKC, Semantic Entropy \\cite{kuhn2023semantic} \\\\'
if old_impl in content:
    content = content.replace(old_impl, new_impl)
    print("Impl table: OK")
else:
    print("WARNING: impl table not found")

with open('paper/remora_paper.tex', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done.")
