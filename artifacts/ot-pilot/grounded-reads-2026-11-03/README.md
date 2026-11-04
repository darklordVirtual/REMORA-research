# OT pilot: the daily-round reads complete without a person (2026-11-03)

Evidence for the WS1 utility milestone. On the OT pilot stack, the five legitimate monitoring reads under the signed daily-round work order complete autonomously. Every write still waits for a `senior_authority` approver, and every negative case in the battery still refuses. Author's runs on one host against a simulated plant; not an independent reproduction and not OT deployment validation.

## What changed between the two batteries

| | Baseline (`dev` before this branch) | This branch, opt-in on | This branch, opt-in off (control) |
|---|---|---|---|
| Tool declaration | none: every tool critical/unknown | `deploy/ot-pilot/tool_metadata.json`: `read_sensor` low and read-only, writes critical, domain `ot_plant` | same |
| `REMORA_GROUNDED_READ_ACCEPT` | unset | `1` | `1` |
| `REMORA_GROUNDED_READ_IN_PRODUCTION` | unset (flag did not exist) | `1` | `0` |
| Monitoring reads completed | 0 of 5 (reviews required: 5) | **5 of 5** (reviews required: 0) | 0 of 5 (reviews required: 5) |
| Battery cases as specified | 16 of 16 | 16 of 16 | 16 of 16 |
| Decision on each read | `verify`, reason `evidence_insufficient` | `accept`, reason `grounded_read_accept`; executed; replay refused with 409 | `verify` |
| Wrong tool under the read-round intent | escalate | escalate | escalate |
| Injection in a maintenance document | escalate | escalate | escalate |
| Writes | review, senior approver, execute, replay 409 | same | same |

The baseline row is `artifacts/ws1/m4/sec99-reproduction/sec99-20261103T194032Z-dee87d1a/battery/`. The other two are `battery-prod/` and `battery-control/` here, each run on a freshly created stack from the same image.

Why the reads were ungrounded before: the pilot declared no tool metadata, so the policy engine saw domain `unknown`. The state index in `ot_bundle.py` (coverage scope `ot_plant`, which lists the five sensors) therefore never applied, and `argument_values_grounded` was false. With the declaration the semantic bundle grounds `sensor_id`, and the one clause left was the production exclusion, which the owner's opt-in lifts (`docs/architecture/ADR-grounded-reads-in-production.md`). The control run shows the opt-in, not the declaration alone, is what completes the reads.

## Same build, the rest of the battery

- `fault-injection/`: `deploy/ot-pilot/run_fault_injection.py` on a fresh stack with the opt-in on, 10 of 10 faults as specified. The faults: restart between approval and execution; spent grant across a restart; cumulative limits across a restart; Postgres stopped during a governed write, and until the API is unhealthy; four concurrent executions of one approval; the same proposal approved twice; stop between approval and execution; a tool failing after dispatch began; approver revoked after approving.
- `sec99-cases/`: the §99 reproduction script against this build with a second process in the executor domain, 11 of 11 cases as the repair specifies. The authority answers 404 to every self-signed lease; the executor answers 403 to the agent token, refuses `lease_unlinked`, records the admitted lease, and refuses `tool_args_hash_mismatch` and `nonce_already_consumed`.

## What this does and does not show

- It shows that, on this stack, grounding from declared data plus the opt-in turns five routine reads from review into completed work without changing any write's path or any negative case's outcome. The policy hash moved (`manifest.json`), as it must when the declaration and the identity flag change.
- It does not show that the reads are correct or free; `_is_grounded_read` asserts only that the call is the declared call for a declared authority over declared data. It does not show anything about WS1 (no WS1 deployment ran here; §94 stays open) or about a real plant.
- The disclosure a production deployment accepts with the opt-in is bounded by the work order, the state index and the declared read-only semantics; it is not zero. The ADR records that.

## Signed ToolSpec and WS1 shadow (2026-11-04)

The pilot was then given a signed ToolSpec bundle
(`deploy/ot-pilot/build_toolspec.py`; the seed stays on the host, the API
holds the public key and the pinned digest). It also got a WS1 deployment in
shadow (`deploy/ot-pilot/ot_ws1.py`, facts in `ot_ws1_facts.json`). `ws1-shadow/assessed.json` is the read-back of the 13 assessed battery calls
from Postgres. Every call carries a ToolSpec hash and a WS1 block. The 5 reads
proved `sensor_on_round` with one lookup each and recorded `grounded_action:
accept`. Of the 8 writes, 6 proved `target_named_by_work_order`; the 2 whose
target no work order names recorded a cap to `abstain` that shadow did not
apply. `battery-toolspec-ws1/` (16 of 16, 5 of 5 reads), `fault-injection-toolspec-ws1/` (10 of 10) and `sec99-cases-toolspec-ws1/` (11 of 11) are the same batteries on that configuration, each on a fresh stack. Limits: shadow changed no decision; `target_named_by_work_order` proves naming by some signed work order, not by the order the call is under, because the pilot's intent authority is the whole work-order file.

## Testing the tests, and labelling the calls (2026-11-04)

Perfect battery scores measured by the author against the author's own cases say little on their own. Two checks were added for that reason.

`mutation-spotcheck.json`: ten hand-written mutants on today's guards, each applied alone with the covering test files run and the file restored. Eight were killed at once. Two survived: the `allow_production` default on the grounded-read predicate (dead code for the engine, which passes the flag explicitly, but unpinned), and the API reading the opt-in from the environment. Two tests were added for them and both mutants are now killed. This is a spot-check, not a sweep; the repository's mutmut configuration covers the enforcement files, not these.

`ws1-shadow/labels.json`: the 13 assessed calls labelled from the battery's own case design and crossed with what WS1 in shadow would have done. WS1 would have capped 2 calls: the valve move under the read-round intent, which is illegitimate, and the battery's tamper case, which is disputed. The tamper case assesses valve V-18 at 35 % and treats that as the legitimate approval, but work order WO-1204 names V-12, so WS1 refuses it on the facts. That is a finding about the battery, and under enforce either the case uses the ordered valve or its expectation changes. WS1 left the injected write alone, which the engine escalates anyway. The labels are the author's; they are not an independent adjudication.

## Reproduce

```
python deploy/ot-pilot/init_tokens.py
python deploy/ot-pilot/build_toolspec.py
docker compose -f deploy/ot-pilot/docker-compose.yml up --build -d
set -a; . deploy/ot-pilot/.env; set +a
python deploy/ot-pilot/run_ot_battery.py
# control: same stack with REMORA_GROUNDED_READ_IN_PRODUCTION set to "0" in an override file
```

Copyright 2026 Stian Skogbrott. Licensed under BUSL-1.1 (`legal/LICENSING.md`); rights ownership in `legal/COPYRIGHT.md`. Concept record: `provenance/concepts/PROV-18.yaml`.
