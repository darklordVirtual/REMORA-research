# Author: Stian Skogbrott
# License: Apache-2.0
"""Fix two failing tests in tests/test_crc.py."""
with open('tests/test_crc.py', encoding='utf-8') as f:
    lines = f.readlines()

out = []
i = 0
while i < len(lines):
    line = lines[i]

    # Fix 1: replace tight_risk test body
    if line.strip().startswith('def test_uniform_weights_tight_risk_unattainable'):
        out.append(line)  # keep def line
        i += 1
        # skip until next def/blank-then-def
        while i < len(lines) and not (
            lines[i].strip().startswith('def ') or
            (lines[i].strip() == '' and i + 1 < len(lines) and lines[i+1].strip().startswith('def '))
        ):
            i += 1
        out.append('    # Cumulative risk at each tier: 1/1=1.0, 2/2=1.0, 2/3>0.10, 2/4=0.5>0.10\n')
        out.append('    scores = [0.9, 0.8, 0.7, 0.6]\n')
        out.append('    labels = [False, False, True, True]\n')
        out.append('    threshold = weighted_conformal_threshold(scores, labels, target_risk=0.10)\n')
        out.append('    assert threshold == UNATTAINABLE_THRESHOLD\n')
        out.append('\n')
        continue

    # Fix 2: replace phase_weights_applied_correctly test body
    if line.strip().startswith('def test_phase_weights_applied_correctly'):
        out.append(line)  # keep def line
        i += 1
        # skip until next non-indented def
        while i < len(lines) and not (
            lines[i].strip().startswith('def ') or
            (lines[i].strip() == '' and i + 1 < len(lines) and lines[i+1].strip().startswith('def '))
        ):
            i += 1
        out.append('    # All 20 items tied at score=0.8: 10 ordered (correct), 10 critical (wrong).\n')
        out.append('    # target=ordered: correct w=1.0, wrong w=0.10\n')
        out.append('    #   weighted_risk = (10*0.10)/(10*1.0+10*0.10) = 1/11 ~ 0.091 <= 0.10 -> attainable\n')
        out.append('    # target=critical: wrong w=1.0, correct w=0.10\n')
        out.append('    #   weighted_risk = (10*1.0)/(10*0.10+10*1.0) = 10/11 ~ 0.91 > 0.10 -> unattainable\n')
        out.append('    phases = ["ordered"] * 10 + ["critical"] * 10\n')
        out.append('    scores = [0.8] * 20\n')
        out.append('    labels = [True] * 10 + [False] * 10\n')
        out.append('\n')
        out.append('    crc_ordered = CovariateShiftCRC(\n')
        out.append('        target_risk=0.10, cal_fraction=1.0, off_distribution_weight=0.10, seed=0\n')
        out.append('    )\n')
        out.append('    report_ordered = crc_ordered.fit(scores, labels, phases=phases, target_phase="ordered")\n')
        out.append('    assert report_ordered.threshold != UNATTAINABLE_THRESHOLD\n')
        out.append('\n')
        out.append('    crc_critical = CovariateShiftCRC(\n')
        out.append('        target_risk=0.10, cal_fraction=1.0, off_distribution_weight=0.10, seed=0\n')
        out.append('    )\n')
        out.append('    report_critical = crc_critical.fit(scores, labels, phases=phases, target_phase="critical")\n')
        out.append('    assert report_critical.threshold == UNATTAINABLE_THRESHOLD\n')
        out.append('\n')
        continue

    out.append(line)
    i += 1

with open('tests/test_crc.py', 'w', encoding='utf-8') as f:
    f.writelines(out)

print("Done")
