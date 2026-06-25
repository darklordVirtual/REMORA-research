# Author: Stian Skogbrott
# License: Apache-2.0
"""Add CRC subsection to paper markdown (section 7)."""

with open('paper/remora_paper.md', encoding='utf-8') as f:
    content = f.read()

# ---- 1. Update conformal related-work paragraph ----
idx_conf = content.find("### 2.5 Conformal Prediction")
if idx_conf >= 0:
    end = content.find("\n### ", idx_conf + 5)
    old_block = content[idx_conf:end]
    new_block = old_block.replace(
        "REMORA implements a Mondrian conformal guardrail",
        "REMORA implements a Mondrian conformal guardrail for the ordered phase "
        "and Conformal Risk Control (Angelopoulos et al., 2022) with importance "
        "weights for the critical phase (§7.2). It also uses a Mondrian conformal guardrail"
    )
    content = content[:idx_conf] + new_block + content[end:]
    print("Related-work conformal MD: OK")
else:
    print("WARNING: 2.5 Conformal section not found")

# ---- 2. Insert CRC subsection as 7.2, renumber 7.2->7.3, 7.3->7.4 ----
# Find where 7.2 Evidence Router begins
marker_72 = "### 7.2 Evidence Router Design"
if marker_72 in content:
    crc_section = """### 7.2 Conformal Risk Control Under Covariate Shift

Standard Mondrian conformal calibration assumes exchangeability between calibration and test samples - a condition violated in the critical phase. Applying standard conformal to critical-phase items yields 100% observed risk and 0% coverage (negative result, §6).

REMORA resolves this with **Conformal Risk Control** (CRC; Angelopoulos et al., 2022), which extends split-conformal prediction to covariate-shifted test distributions via per-item importance weights. For the phase-shift setting, REMORA uses:

$$w_i = \\begin{cases} 1.0 & \\text{if phase}(i) = p_{\\text{test}} \\\\ \\beta = 0.10 & \\text{otherwise} \\end{cases}$$

The CRC threshold $\\hat{\\lambda}$ minimises accepted items subject to weighted empirical risk $\\bar{L}(\\hat{\\lambda}) \\leq \\alpha$. **Theorem 1** (Angelopoulos et al., 2022) guarantees:

$$\\mathbb{E}[L(\\hat{\\lambda})] \\leq \\alpha + \\frac{1}{n+1}$$

For binary 0/1 loss, the overshoot above $\\alpha$ is at most $1/(n+1)$ - 5 pp for $n=19$, 1 pp for $n=99$.

Implementation: `remora.selective.crc.CovariateShiftCRC.fit(scores, labels, phases, target_phase)` returns a `CRCReport` with `finite_sample_slack` ($= 1/(n_{\\text{cal}}+1)$) and `guaranteed_risk_bound` ($= \\alpha + \\text{slack}$). Tested: 44 unit tests covering edge cases, tied-score atomicity, phase-weight algebra, and Theorem 1 slack.

"""
    # Renumber 7.2 -> 7.3 and 7.3 -> 7.4
    content = content.replace("### 7.3 Evidence Signal Provenance", "### 7.4 Evidence Signal Provenance")
    content = content.replace("### 7.2 Evidence Router Design", "### 7.3 Evidence Router Design")
    # Insert CRC section
    content = content.replace("### 7.3 Evidence Router Design", crc_section + "### 7.3 Evidence Router Design")
    print("CRC subsection MD: OK")
else:
    print("WARNING: ### 7.2 Evidence Router Design not found")

with open('paper/remora_paper.md', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
