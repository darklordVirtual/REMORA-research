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

## Recorded runs of the simulated OT plant

`deploy/ot-pilot/` runs REMORA in production mode beside a simulated plant
(`ot_registry.py`: sensors, two control loops, two valves, alarms, work
orders) with signed, mandatory cumulative limits. `run_ot_battery.py` drives
16 cases over HTTP and writes an evidence run. One run is committed.

| Run | Built from | Cases | Side effects | Chains |
|---|---|---|---|---|
| [`runs/ot-battery-2026-10-25/`](runs/ot-battery-2026-10-25/) | image from master `0f30a49e`; battery from the branch that added the limit case | 16 of 16 as specified | 6 executed | tenant audit chain and envelope chain valid |

What the run shows, and what it does not: five monitoring reads resolve to
VERIFY. Five governed writes run only after a separate approver token
approves them. The operator token's own approval is refused with 403, and a
replay of each spent grant is refused with 409. An approved valve move
executed with other arguments is refused as `binding_refused`. A wrong tool
for the work order and an injected instruction resolve to ESCALATE. A tool
with no limit meter, a loop the plant does not report and a setpoint move
past the hourly cap are refused at assess, before any decision
(`limit_coverage_unknown`, `limit_observation_unavailable`,
`limit_exceeded`). The plant is simulated and the run is on one host. The
manifest records the commit as `local` because the battery runs where git is
unavailable; the table above names the commit.

## Fault injection through the whole chain

`deploy/ot-pilot/run_fault_injection.py` breaks the running pilot while it
works and records what the chain did. It drives the API over HTTP and the
stack through `docker compose`. Each of nine faults states what the system
must do, and a fault that does otherwise is reported as a failure.

1. The API restarts between an approval and its execution.
2. A spent grant is replayed after a restart.
3. Cumulative limits are checked across a restart.
4. PostgreSQL is stopped during a governed write.
5. Four executions of one approval race each other.
6. The same write is proposed and approved twice.
7. Execution is stopped between an approval and its execution.
8. A tool fails after dispatch began.
9. An approver is revoked after approving.

Every run records the configuration it ran against: the sha256 of the
compose file, Dockerfile, limit policy, work orders, plant registry and
semantic bundle, the API image id, the commit and the policy hash. Two runs
with the same fingerprint ran the same deployment. Each run also measures
latency by route, writes completed against writes intended, refusals of
writes that should have run, and the human steps the run needed.

| Run | Built from | Faults | Writes | Chains |
|---|---|---|---|---|
| [`runs/fault-injection-2026-10-26-before-fixes/`](runs/fault-injection-2026-10-26-before-fixes/) | master `92aa1e3e` with the runner's working tree | 7 of 9 as specified | 7 of 8 | both valid, 44 execution records |
| [`runs/fault-injection-2026-10-26/`](runs/fault-injection-2026-10-26/) | `20b9b012`: master `e6e5a765` (#1079, #1080) with this runner; fingerprint `bc4522e5` | 9 of 9 as specified | 8 of 8, no false refusals, 14 human steps | both valid, 44 execution records |

The first run found two defects, and both were fixed before the second run:

- **The stop spent the approval.** A stop between approval and execution
  held, and no effect ran, but `/execute` spent the approval. The item
  answered 409 after the resume (#1079).
- **A store outage was a bare 500.** With PostgreSQL stopped, assess and
  execute refused without an effect, but both answered a bare 500 that a
  client cannot tell from a defect (#1080). In the second run they answer
  503: assess with `durable_state_unavailable`, and execute with
  `execution_stop_unverifiable`, because it now reads the stop flag first.
  After recovery the approved write ran once, from the plant's starting
  value.

The same run directory holds a battery run on a fresh stack with the same
configuration: 16 of 16 cases, 6 side effects, both chains valid
(`battery-same-configuration.json`).

The faults also show what holds:

- An approval survives a restart, and a spent grant stays spent.
- The limit ledger still counts a move made before the restart.
- Exactly one of four racing executions runs.
- A revoked approver's approval is invalidated.
- A tool that fails after dispatch began leaves the outcome UNKNOWN and its
  limit reservation held. A reviewer then resolves it, and the resolution is
  checked against the plant's log (`ot_registry.check_limit_evidence`,
  `REMORA_LIMITS_EVIDENCE_MODULE`). Before this runner the pilot had no
  evidence reader, so such a reservation could never be released.

What the runs do not show:

- **A proposal approved twice runs twice.** The pilot's limit policy
  declares no idempotency keys. Closing that needs the policy re-signed with
  `idempotency.key_arguments` and `REMORA_REQUIRE_IDEMPOTENCY=1`, and the
  signing key is held by the pilot's limit authority, not this repository.
- **The setup is minimal.** The plant is simulated in the API process and
  resets on a restart. There is one host, one replica and the SQLite limit
  ledger.
- **The latencies are not a performance claim.** They come from one local
  Docker host. Calls made while PostgreSQL was down are reported apart, under
  `[fault window]`.
- **`GET /v1/health` reports only liveness.** It answers `ok` while the store
  is down.
