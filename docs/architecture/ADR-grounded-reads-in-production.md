# ADR: grounded reads may complete in production, opt-in

- Status: **accepted** (owner decision 2026-11-03, recorded in the WS1 utility milestone PR)
- Scope: `remora/policy/decision_engine.py` flag `grounded_read_in_production`; `REMORA_GROUNDED_READ_IN_PRODUCTION` on the execution API; the OT pilot's compose file
- Related: NEGATIVE_RESULTS §94, `docs/07-api-reference.md` (intent authority), `deploy/gateway/tool_metadata.json` `_reads`

## Context

The grounded-read path (`GROUNDED_READ_ACCEPT`, opt-in since 2026-08-06) lets a read execute without a person when every question the engine can answer from declared data is answered positively: read-only semantics, low tier, a server-resolved work order, and all four grounding signals. It excluded production targets, because the blast radius of a read in production includes disclosure of live data to the agent.

The OT pilot runs in production mode against a simulated plant. Its five daily-round sensor reads all went to review (OT battery 2026-11-03: 0 of 5 monitoring reads completed, 16 of 16 cases as specified). Two things caused that. The pilot declared no tool metadata, so every tool was critical/unknown and the state index never applied; that is a declaration gap, fixed by `deploy/ot-pilot/tool_metadata.json`. And the production exclusion stood, which is policy.

The gateway's `_reads` note records the earlier lesson: the tier says what a tool does, the environment says where, and a test deployment should not call itself production. That lesson holds. This decision is about deployments that are production and still want their routine reads to run.

## Decision

A deployment may opt in to grounded reads for production targets. The engine gains `grounded_read_in_production` (default off), read from `REMORA_GROUNDED_READ_IN_PRODUCTION` on the execution surface. It is part of the policy identity (`ENGINE_IDENTITY_FLAGS`), so a deployment that turns it on reports a different policy hash.

The flag lifts exactly one clause of the grounded-read path: the target-environment exclusion. Every other clause stands, and the low-consequence path is untouched and keeps excluding production.

The OT pilot turns it on. Its `read_sensor` is declared low tier and read-only in `tool_metadata.json`; every write stays critical and goes to a `senior_authority` approver.

## Consequences

- A production deployment that enables the flag accepts that a grounded read discloses live data to the agent without a person in the loop. The disclosure is bounded by the work order the read is made under, the state index, and the tool's declared read-only semantics; it is not zero.
- Nothing becomes more approvable for writes, for medium or higher tiers, for calls without a resolved authority, or for calls with any grounding signal unknown or false.
- The policy hash changes, so leases issued before the flag was set do not redeem after it.
- Measured on the pilot before any claim is made: the OT battery with the flag on, the fault-injection battery, and the §99 cases. The numbers live in `artifacts/ot-pilot/`, not here.

## Alternatives considered

- Declare the pilot's environment as staging. Honest for a simulated plant, and it would have reached the same reads with no engine change. Rejected as the only remedy because it answers nothing for a real production site, which is the deployment this repository is for.
- Enable WS1 enforce with grounding from proofs (§94). Blocked until flow control's IFC-13 has evidence, and the pilot has no signed ToolSpec bundle yet. Kept as the next step; WS1 shadow on the pilot measures what it would add.
- Lower the writes' tiers. Rejected: a tier states what a tool does.
