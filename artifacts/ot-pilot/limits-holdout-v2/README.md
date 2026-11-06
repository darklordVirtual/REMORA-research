# Limits holdout v2

Plan: `docs/assurance/ot_limits_holdout_plan_v2.md` (DOC-427). The authors read the v1 brief, unchanged (`../limits-holdout-v1/author-brief.md`, SHA-256 `5b984a68da6c1d13e6e5272185675013cfa993ab8d4250bdfdbe1d2f13d2783f`). The prompts are v1's holdout prompts (`../limits-holdout-v1/author-prompts.md`), with only the label and the output file changed:

| Session | Label | Shifts | Profile as in v1 | File |
|---|---|---:|---|---|
| holdout C | `hC` | 20 | set A (steady day shifts) | `holdout/shifts-C.json` |
| holdout D | `hD` | 20 | set B (busy night and weekend shifts) | `holdout/shifts-D.json` |

Each session reported two tool calls: reading the brief and writing its file. They were started with the agent tool from this checkout, as in v1. The operator's saved memory then held v1's result and v1's FIC-220 bound, but no v2 bound. The plan records that before the data.
