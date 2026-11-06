# Limits holdout v3

Plan: `docs/assurance/ot_limits_holdout_plan_v3.md` (DOC-428). The authors read the v1 brief, unchanged (`../limits-holdout-v1/author-brief.md`). The prompts are v1's holdout prompts with the label, the output file and one instruction changed: every shift contains a stop of delivery and a later restart, for a reason the shift gives.

| Session | Label | Shifts | Profile as in v1 | File |
|---|---|---:|---|---|
| holdout E | `hE` | 20 | set A (steady day shifts) | `holdout/shifts-E.json` |
| holdout F | `hF` | 20 | set B (busy night and weekend shifts) | `holdout/shifts-F.json` |

Each session reported two tool calls: reading the brief and writing its file. They were started with the agent tool from this checkout. The operator's saved memory then held v1's and v2's results, including that v2's refusals were PIC-101 around stops, but no v3 policy detail. The plan records that before the data.
