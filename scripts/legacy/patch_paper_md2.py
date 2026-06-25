# Author: Stian Skogbrott
# License: Apache-2.0
"""Patch Section 7.1 in remora_paper.md with PhaseAwareGuardrail details."""

with open('paper/remora_paper.md', encoding='utf-8') as f:
    content = f.read()

# Find the critical-phase paragraph
start_marker = 'In the critical phase, oracle consensus is near the phase boundary'
end_marker = '\n\n### 7.2 Evidence Router Design'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker, start_idx)

if start_idx < 0:
    print("ERROR: start marker not found")
    exit(1)
if end_idx < 0:
    print("ERROR: end marker not found")
    exit(1)

old_para = content[start_idx:end_idx]
print("Found paragraph:", repr(old_para[:100]))

new_para = (
    'In the critical phase, oracle consensus is near the phase boundary: the trust score is moderate '
    'but neither reliably high nor reliably low. A key empirical finding (§13.3) is that in this phase, '
    '*higher trust scores correlate with lower correctness* (Q4 high-trust: 50% correct vs Q1 low-trust: '
    '75% correct on N=32 real-oracle critical-phase items; refined: τ ≥ 0.10 → 27.3% accuracy, '
    'τ < 0.10 → 71.4% accuracy, N=21). This is the opposite of what trust-based routing assumes. '
    'Conformal calibration at 5% risk target fails completely on critical-phase items '
    '(mean observed risk = 100%, coverage → 0%). Trust scoring alone cannot gate critical-phase decisions.\n\n'
    '**PhaseAwareGuardrail: Exploiting the Inversion.** The inversion is a *selection criterion reversal*: '
    'the guardrail should prefer low-τ items in the critical phase. `PhaseAwareGuardrail` '
    '(implemented in `remora.selective.guardrail`) applies an inverted score `τ̃ = 1 - τ` '
    'for critical-phase items, then calibrates a conformal threshold on `τ̃`. A hard gate rejects '
    'all items with τ ≥ 0.10 (the groupthink boundary). The combined pool '
    '(99 ordered + 21 low-τ critical items) achieves:\n\n'
    '| Coverage | N   | Accuracy | Wilson CI       | Lift over baseline |\n'
    '|----------|-----|----------|-----------------|--------------------|\n'
    '| 18.2%    | 99  | 86.9%    | [78.8%, 92.2%]  | +45.7 pp           |\n'
    '| 20.0%    | 108 | 85.2%    | [77.3%, 90.7%]  | +44.0 pp           |\n'
    '| **22.1%**| **120** | **84.2%** | **[76.6%, 89.6%]** | **+43.0 pp** |\n\n'
    'A +3.9 pp coverage gain with 2.7 pp accuracy cost; still +43 pp above the 41.18% baseline. '
    'The guardrail is fully implemented and tested (8 unit tests in `tests/test_guardrail.py`).'
)

content = content[:start_idx] + new_para + content[end_idx:]
print("Updated: OK" if new_para in content else "ERROR: update failed")

with open('paper/remora_paper.md', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done.")
