# REMORA pilot pack v1

The standardised package a pilot partner receives (issue #90); the
operational wrapping around
[`docs/validation/pilot_evaluation_protocol_v1.md`](../../docs/validation/pilot_evaluation_protocol_v1.md).
Everything here serves the protocol's preconditions; nothing here relaxes
them. Shadow mode, observer-only, bounded scope.

| File | Serves precondition | What it is |
|---|---|---|
| `example-config/shadow-mode.env` | 2, 3, 7 | Bounded shadow-mode deployment configuration for the [container reference deployment](../../docs/deployment/container-reference.md) (issue #89 — the delivery vehicle) |
| `example-config/partner_tool_registry.py` | 3, 4 | Worked example of the `REMORA_TOOL_REGISTRY_MODULE` contract: the partner's tools with explicit risk/action metadata — name inference never drives verdicts that count |
| `event_schema.json` | 4, 5 | JSON Schema for the events the partner supplies: tool call + registry metadata + ground-truth label, aligned with `PolicyObservation.from_tool_call` and the DecisionEnvelope |
| `export_envelopes.py` | reporting | Export recipe / minimal dashboard over the envelope stream: the protocol's selectivity, stability and technical metrics with denominators |
| `evaluation_worksheet.md` | 6 | The go/no-go table as a fill-in worksheet — thresholds are frozen BEFORE the first scored event and the frozen date is part of the worksheet |

## How a pilot runs

1. Deploy the locked container (`deploy/reference/`), configure from
   `shadow-mode.env`, wire the partner registry module.
2. Freeze the worksheet thresholds with the partner; record the date.
3. Stream events; every scored event keeps its `DecisionEnvelope`
   (`GET /v1/envelope/{request_id}`, durable when
   `REMORA_CONTROL_PLANE_DB`/`_DSN` is set; the shadow-mode env sets it).
4. Export metrics with `export_envelopes.py`; fill the worksheet against
   the frozen thresholds; stop conditions apply as written in the protocol.

A pilot is not successful because the system ran; see the protocol's
success definition. Negative findings are reported with the same
prominence as positive ones.
