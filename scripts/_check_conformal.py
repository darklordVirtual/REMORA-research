# Author: Stian Skogbrott
# License: Apache-2.0
"""Validate conformal-related artifacts and consistency checks used in REMORA quality gates."""
import json
d = json.load(open("results/conformal_guardrail_holdout.json"))
print("n =", d["n"])
for k, v in d["reports"].items():
    print(f"  target={k}  holdout_risk={v['holdout_risk']:.4f}  coverage={v['holdout_coverage']:.4f}")
