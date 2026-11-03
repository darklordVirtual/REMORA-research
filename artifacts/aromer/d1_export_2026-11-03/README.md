# AROMER D1 export, 2026-11-03

**Status:** archived research data. Not a validated benchmark. Not a labelled
harm dataset.

**Exported:** 2026-11-03 from the live AROMER Worker database (`aromer-episodes`)
with `scripts/aromer_export.sh` (mode `export`, nothing deleted). Data,
provenance, verification checks, sanitization rules and label provenance are in
one file: [`aromer_d1_export_2026-11-03.json`](aromer_d1_export_2026-11-03.json)
(schema `aromer_d1_export_v1`).

## Why this export exists

The AROMER Worker cron ran every 5 minutes from June to November 2026. No new
episodes arrived after **2026-07-02**; from then on each run re-scored the same
200-episode sample and re-critiqued the same episodes. The deployed schedule
(`*/5`) did not match the schedule in `workers/aromer/wrangler.toml`
(`0 */4 * * *`). This export preserves the data before the loop is stopped and
the duplicate log rows are pruned.

## Contents

| Key in `aromer_d1_export_2026-11-03.json` | Rows | What it is |
|---|---|---|
| `intelligence_scores_daily` | 153 | Last AII/ECE/calibration snapshot per UTC day, 2026-06-04 → 2026-11-03 (reduced from 37,698 rows) |
| `world_model_priors` | 198 | Beta(α, β) priors per (domain, action_type, risk_tier) at export time |
| `oracle_bandit_state` | 3 | Oracle bandit state at export time |
| `verification` | n/a | 13/13 checks against values read from the live database before export |
| `reduction`, `sanitization`, `label_provenance` | n/a | How rows were reduced and sanitized, and where labels come from |
| `public_episode_file` | n/a | Size, row count and SHA-256 of the episode file kept outside git |

`episodes_public.jsonl` (21,864 rows, 15.2 MB, SHA-256 `a11abfac…2db3`) is
**not committed** to git because of its size. It is hosted with the dataset
release; its hash is pinned under `public_episode_file.sha256`.

## Longitudinal AII (daily last snapshot)

| Month | Days | AII min | AII max |
|---|---|---|---|
| 2026-06 | 27 | 0.4066 | 0.9851 |
| 2026-07 | 31 | 0.9897 | 0.9918 |
| 2026-08 | 31 | 0.9901 | 0.9914 |
| 2026-09 | 30 | 0.9901 | 0.9914 |
| 2026-10 | 31 | 0.9908 | 0.9914 |
| 2026-11 | 3 | 0.9914 | 0.9914 |

**Caveat:** the flat AII from July onward reflects a frozen 200-episode sample,
not continued learning or validation. It must not be cited as evidence of
stability under new data.

## Label provenance (read before using the episodes)

| Source | Rows | ground_truth |
|---|---|---|
| Claude Code PreToolUse recorder hook | 18,249 | 17,539 benign · 710 unknown · **0 harmful** |
| Seed feeds, public benchmarks, `/decide` tests, episode factory | 3,615 | 2,604 benign · 28 unknown · 983 harmful |

Recorder-hook labels are presumed-benign defaults (15,657 with no
`label_source`, 1,881 `ttl_presumed_benign`) or TTL expiries. They are **not**
human or oracle adjudications. The hook episodes are a corpus of real, mostly
routine agent tool calls (Read, Bash, PowerShell, Edit, MCP tools), suitable for
friction / false-block-rate measurement on benign traffic. All 983 harmful labels
come from seeds, public benchmarks (CaiZhiTech/guardrails,
aradhye/agent-safety-bench) and endpoint tests; their redistribution terms follow
the upstream licences.

## Sanitization

Removed before publication: `critique_text`, the raw tool input
(`meta.input_preview`, first 200 chars of each tool call, recorded before the
redaction added on 2026-10-29), `session_id`, paths, commands and any meta
string longer than 80 characters or matching secret, path or e-mail patterns.
A residual scan found 0 hits. A leak test of 145,050 unique 20-character windows
from the raw previews found 60 overlaps in the public file; all were reviewed and
are tool names, dataset names, seed-script names, one generic git command and two
deliberate prompt-injection test strings. The unsanitized export is retained
privately and is not part of this repository.

## Reproduce

```bash
npx wrangler login
scripts/aromer_export.sh            # export + verification; deletes nothing
```

The script exits before packaging if any of the 13 reference checks fails.
Reference values are specific to the 2026-11-03 state of the database.
