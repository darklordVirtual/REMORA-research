# Pilot evaluation worksheet (fill-in)

Instance of the go/no-go framework in
[`docs/validation/pilot_evaluation_protocol_v1.md`](../../docs/validation/pilot_evaluation_protocol_v1.md).
**Thresholds are frozen before the first scored event.** The frozen values
and the freeze date are part of the record; changing a threshold after data
is in invalidates the run.

| Field | Value |
|---|---|
| Partner |  |
| Pilot scope (named tools/workflows) |  |
| Protocol version | pilot_evaluation_protocol_v1 |
| Container image digest (release notes) |  |
| Thresholds frozen on (date, by whom) |  |
| Scoring window |  |

## Go / no-go (fill measured values with denominators)

| Criterion | Frozen threshold | Measured | Pass? |
|---|---|---|---|
| Technical completion (events assessed / relevant events) |  |  |  |
| Missing audit data |  |  |  |
| Replay stability (deterministic agreement where expected) |  |  |  |
| Human-review agreement, per risk class |  |  |  |
| Inter-rater agreement (reported alongside) |  |  |  |
| False-positive rate |  |  |  |
| Critical false negatives (each with analysis) |  |  |  |
| Review workload (events/reviewer, time/event) |  |  |  |
| Explainability (share of reviewers rating explanations understandable) |  |  |  |

## Stop-condition log

| Date | Condition triggered | Action taken | Resumed? |
|---|---|---|---|
|  |  |  |  |

## Verdict

- [ ] GO: criteria met against frozen thresholds
- [ ] NO-GO: with the failed criteria and their measured values listed
- Negative findings reported with the same prominence as positive ones:

> _Findings:_
