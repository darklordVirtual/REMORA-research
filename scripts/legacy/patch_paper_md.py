# Author: Stian Skogbrott
# License: Apache-2.0
"""Patch remora_paper.md to add phase-aware operating point."""

with open('paper/remora_paper.md', encoding='utf-8') as f:
    content = f.read()

# 1. Update abstract
old_abstract_snippet = (
    'REMORA achieves 88.8% selective accuracy at 18% coverage '
    '(majority-vote full-coverage baseline: 41.18%; +47.6 percentage-point lift; in-sample optimum). '
    'A stratified 80/20 held-out evaluation with threshold τ* locked from the training split confirms '
    '**88.0% accuracy at 23.2% holdout coverage** (N\\_accepted = 25, Wilson CI [70.0%, 95.8%], '
    'p = 1.45 × 10⁻⁵), establishing that the result is not an artefact of in-sample threshold selection.'
)
new_abstract_snippet = (
    'REMORA achieves 88.8% selective accuracy at 18% coverage '
    '(majority-vote full-coverage baseline: 41.18%; +47.6 pp lift; in-sample optimum). '
    'Exploiting the empirically confirmed critical-phase trust inversion (low-τ critical items achieve '
    '71.4% accuracy vs. 27.3% for high-τ), a `PhaseAwareGuardrail` with inverted-score selection '
    'extends coverage to **22.1% at 84.2% accuracy** (+43.0 pp lift; N=120; Wilson CI [76.6%, 89.6%])-'
    'a +3.9 pp coverage gain with only 2.7 pp accuracy cost. '
    'A stratified 80/20 held-out evaluation with threshold τ* locked from the training split confirms '
    '**88.0% accuracy at 23.2% holdout coverage** (N\\_accepted = 25, Wilson CI [70.0%, 95.8%], '
    'p = 1.45 × 10⁻⁵), establishing that the result is not an artefact of in-sample threshold selection.'
)
if old_abstract_snippet in content:
    content = content.replace(old_abstract_snippet, new_abstract_snippet)
    print("Abstract: OK")
else:
    print("WARNING: abstract snippet not found")

# 2. Update conclusion key findings
old_finding = (
    '- Thermodynamic routing achieves 88.8% selective accuracy at 18% coverage on the QA benchmark '
    '(+47.6 pp over full-coverage majority vote; in-sample calibration caveat applies).'
)
new_finding = (
    '- Thermodynamic routing achieves 88.8% selective accuracy at 18% coverage on the QA benchmark '
    '(+47.6 pp over full-coverage majority vote; in-sample calibration caveat applies). '
    'A `PhaseAwareGuardrail` exploiting the critical-phase trust inversion extends coverage to 22.1% '
    'at 84.2% accuracy (+43.0 pp lift), adding 21 low-τ critical items via inverted-score selection.'
)
if old_finding in content:
    content = content.replace(old_finding, new_finding)
    print("Conclusion finding: OK")
else:
    print("WARNING: conclusion finding not found")

# 3. Update the critical-phase problem section to mention PhaseAwareGuardrail
old_critical = (
    '### 7.1 The Critical-Phase Problem'
)
new_critical_section = (
    '### 7.1 The Critical-Phase Problem and PhaseAwareGuardrail'
)
if old_critical in content:
    content = content.replace(old_critical, new_critical_section)
    print("Section 7.1 title: OK")
else:
    print("WARNING: section 7.1 title not found")

# 4. Find and update the critical-phase description paragraph
old_crit_para = (
    'Trust scores in the critical phase anti-correlate with correctness '
    '(Q4 high-trust items: 50% correct vs Q1 low-trust: 75% correct).'
)
new_crit_para = (
    'Trust scores in the critical phase anti-correlate with correctness '
    '(Q4 high-trust items: 50% correct vs Q1 low-trust: 75% correct; '
    'empirically: τ ≥ 0.10 → 27.3% accuracy, τ < 0.10 → 71.4% accuracy). '
    'This is a *selection criterion reversal*: the guardrail should prefer low-τ items.\n\n'
    'A `PhaseAwareGuardrail` (implemented in `remora.selective.guardrail`) exploits this by '
    'applying an inverted score `τ̃ = 1 - τ` for critical-phase items and calibrating a '
    'conformal threshold on `τ̃`. A hard gate rejects all items with τ ≥ 0.10 (the groupthink '
    'boundary). The combined pool (99 ordered + 21 low-τ critical items) achieves:\n\n'
    '| Coverage | N   | Accuracy | Wilson CI       | Lift    |\n'
    '|----------|-----|----------|-----------------|---------|\n'
    '| 18.2%    | 99  | 86.9%    | [78.8%, 92.2%]  | +45.7pp |\n'
    '| 20.0%    | 108 | 85.2%    | [77.3%, 90.7%]  | +44.0pp |\n'
    '| 22.1%    | 120 | 84.2%    | [76.6%, 89.6%]  | +43.0pp |\n\n'
    'A +3.9 pp coverage gain with 2.7 pp accuracy cost; still +43 pp above the 41.18% baseline.'
)
if old_crit_para in content:
    content = content.replace(old_crit_para, new_crit_para)
    print("Critical-phase paragraph: OK")
else:
    print("WARNING: critical-phase paragraph not found")
    idx = content.find('Trust scores in the critical phase')
    print("Context:", repr(content[idx:idx+200]) if idx >= 0 else "NOT FOUND")

with open('paper/remora_paper.md', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done.")
