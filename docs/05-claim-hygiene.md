# What is the decision rule for adding a claim?

This document defines what REMORA may and may not claim from AgentHarm runs,
and which artifact must exist before any claim leaves draft status.

## Decision rule

A headline external-guardrail claim is permitted only when all of the following
hold:

1. `results/agentharm/guardrail_scores.json` exists with `"status": "ok"`.
2. A baseline arm ran on the full harmful split and the full benign split, not a
   `--limit` pilot, with completed samples in both.
3. At least one REMORA arm, normally `remora_full`, ran on the same splits.
4. `results/agentharm/tool_probe.json` shows
   `tools_beyond_submit_exposed: true`. Otherwise the run is intent-gating only.
5. `results/agentharm/mode_metadata.jsonl` shows `degraded: false` for the arm
   being claimed.
6. The wording follows the permitted scoped templates below.

If any condition fails, the result is roadmap / not-yet-validated, not a claim.

## Forbidden claims without matching artifacts

| # | Forbidden statement | Why it is forbidden | Artifact that could license a weaker scoped version |
|---|---------------------|---------------------|-----------------------------------------------------|
| 1 | "REMORA blocks N% of harmful agent actions." | Implies tool-call interception. Current harness is intent-gating until proven otherwise. | `tool_probe.json: tools_beyond_submit_exposed=true`, a verified tool wrapper, and recall on the full split. |
| 2 | "REMORA achieves recall > 0.852 / precision > 0.974 / FPR < 0.023." | Those are external reference numbers, not validated REMORA results. | Full harmful and benign run with `status:ok` and a documented head-to-head protocol. |
| 3 | "REMORA is production-certified / safety-guaranteeing." | No certification exists; this violates the project charter. | Never. This is permanently forbidden. |
| 4 | "REMORA intercepts every tool call." | Not demonstrated by the current solver. | Real PreToolUse hook verified by the probe. |
| 5 | "Validated on AgentHarm." | A pilot with `--limit` or a degraded arm is not validation. | Full-split run, `degraded:false`, `status:ok`, and reproduced by `run_full.sh`. |

## Permitted scoped wording

- "On a pilot of N harmful / M benign AgentHarm samples, REMORA's intent-gating
  recorded `DecisionEnvelope` artifacts for the proposed action surface. This is
  not a tool-call interception result."
- "REMORA's deterministic hard blocks fired on K proposed actions. Oracle-backed
  modes were unavailable or degraded, so no oracle-consensus claim is made."

## Reviewer note

Threshold flags in `guardrail_scores.json`, such as `meets_recall` or
`publishable`, are internal informational flags. They do not authorize external
statements. Only the decision rule above does.

## Citation status

All in-text citations have complete Reference section entries. Previously
flagged gaps (Wang et al. 2023, El-Yaniv & Wiener 2010, Raji et al. 2022)
were resolved and added to the References section on 2026-06-28.
