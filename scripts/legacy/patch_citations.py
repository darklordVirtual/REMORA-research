# Author: Stian Skogbrott
# License: Apache-2.0
"""Task #15: Verify and fix citations in paper.

1. Add missing cite{kuhn2026evse} in SE text
2. Verify all 5 new bibliography entries are correct format
3. Verify all cites are used
"""
import re

with open('paper/remora_paper.tex', encoding='utf-8') as f:
    tex = f.read()

# ---- 1. Add kuhn2026evse cite alongside first kuhn2023semantic cite ----
# The first cite is in the Stage 3 paragraph about NLISemanticBackend
old_cite1 = (
    'cross-encoder entailment clustering, implementing Semantic Entropy\n'
    r'\cite{kuhn2023semantic}. Oracle weights are derived from'
)
new_cite1 = (
    'cross-encoder entailment clustering, implementing Semantic Entropy\n'
    r'\cite{kuhn2023semantic,kuhn2026evse}. Oracle weights are derived from'
)
if old_cite1 in tex:
    tex = tex.replace(old_cite1, new_cite1)
    print("Added kuhn2026evse cite in Stage 3: OK")
else:
    print("WARNING: Stage 3 SE cite not found")

# ---- 2. Verify all 5 new bibitem entries are present ----
required = ['kuhn2023semantic', 'kuhn2026evse', 'kirsch2024prover', 'angelopoulos2022crc', 'zhang2025tee']
for key in required:
    if f'\\bibitem{{{key}}}' in tex:
        # Count usages
        usages = len(re.findall(r'\\cite\{[^}]*' + re.escape(key), tex))
        print(f"{key}: bibitem OK, {usages} cite usage(s)")
    else:
        print(f"WARNING: bibitem {{{key}}} MISSING from bibliography")

with open('paper/remora_paper.tex', 'w', encoding='utf-8') as f:
    f.write(tex)

print("Done")
