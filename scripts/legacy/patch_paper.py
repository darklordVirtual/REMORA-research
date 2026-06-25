# Author: Stian Skogbrott
# License: Apache-2.0
"""Patch remora_paper.tex to add phase-aware operating point."""

with open('paper/remora_paper.tex', encoding='utf-8') as f:
    content = f.read()

# 1. Add phase-aware row to Table 1
old_row = (
    'neg-temp. (18\\%)$\\dagger$     & in-sam & 18\\%   & \\textbf{88.78\\%} & \\textbf{+47.6} & [81.0, 93.6] \\\\\n'
    'neg-temp. (25\\%)$\\dagger$     & in-sam & 25\\%   & 72.79\\% & +31.6 & [64.8, 79.6] \\\\'
)
new_row = (
    'neg-temp. (18\\%)$\\dagger$     & in-sam & 18\\%   & \\textbf{88.78\\%} & \\textbf{+47.6} & [81.0, 93.6] \\\\\n'
    'phase-aware (22\\%)$\\S$        & in-sam & 22.1\\% & 84.2\\%  & +43.0 & [76.6, 89.6] \\\\\n'
    'neg-temp. (25\\%)$\\dagger$     & in-sam & 25\\%   & 72.79\\% & +31.6 & [64.8, 79.6] \\\\'
)
if old_row in content:
    content = content.replace(old_row, new_row)
    print("Table row: OK")
else:
    print("WARNING: table row not found")

# 2. Update table caption
old_caption = (
    '\\caption{QA benchmark selective accuracy ($N=544$). $\\dagger$~In-sample\n'
    'optimum; $\\ddagger$~held-out: stratified 80/20 split, $\\tau^*=0.203$\n'
    'locked from training set (seed=42).}'
)
new_caption = (
    '\\caption{QA benchmark selective accuracy ($N=544$). $\\dagger$~In-sample\n'
    'optimum; $\\ddagger$~held-out: stratified 80/20 split, $\\tau^*=0.203$\n'
    'locked from training set (seed=42); $\\S$~\\texttt{PhaseAwareGuardrail}:\n'
    'ordered~$+$~inverted low-$\\tau$ critical ($\\tau < 0.10$), $N=120$.}'
)
if old_caption in content:
    content = content.replace(old_caption, new_caption)
    print("Caption: OK")
else:
    print("WARNING: caption not found")

# 3. Update phase breakdown paragraph
old_breakdown = (
    'Phase breakdown on full dataset:\n'
    'ordered (N=99): 86.9\\%; critical (N=32): 62.5\\%; disordered (N=413): 28.6\\%.\n'
    'Disordered items constitute 75.9\\% of the benchmark, driving the\n'
    'low full-coverage baseline---a structural property of benchmark\n'
    'composition.'
)
new_breakdown = (
    'Phase breakdown on full dataset:\n'
    'ordered (N=99): 86.9\\%; critical (N=32): 62.5\\%; disordered (N=413): 28.6\\%.\n'
    'Disordered items constitute 75.9\\% of the benchmark, driving the\n'
    'low full-coverage baseline---a structural property of benchmark\n'
    'composition. Extending coverage beyond the ordered-only 18.2\\% operating\n'
    'point requires exploiting the critical-phase trust inversion\n'
    '(\\S\\ref{sec:phase_aware}): the \\texttt{PhaseAwareGuardrail} raises\n'
    'coverage to 22.1\\% at 84.2\\% accuracy by adding 21 low-$\\tau$ critical\n'
    'items ($\\tau < 0.10$, inverted-score selection, $+43.0$\\,pp lift).'
)
if old_breakdown in content:
    content = content.replace(old_breakdown, new_breakdown)
    print("Phase breakdown: OK")
else:
    print("WARNING: phase breakdown not found")
    idx = content.find('Phase breakdown')
    print("Context:", repr(content[idx:idx+300]))

with open('paper/remora_paper.tex', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done.")
