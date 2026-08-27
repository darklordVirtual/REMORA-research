# REMORA product packaging

REMORA is an authorization, policy and evidence layer between an AI agent's
proposed tool action and privileged execution. This document defines the
commercial stages and binds every stage to the machine-validated deployment
maturity in [`../assurance/release_profiles_v1.yaml`](../assurance/release_profiles_v1.yaml).
Nothing here may advertise a stage stronger than the CI-validated
`current_profile`.

## Product stages

| Stage | Release profile binding | Offered today |
|---|---|---|
| Research / Evaluation | `RESEARCH_REFERENCE` | Yes — source-available repository |
| **REMORA Shadow Pilot** | `SHADOW_PILOT` (= `SHADOW_ONLY`) | **Yes — primary offering** |
| REMORA Controlled Enforcement | `CONTROLLED_PILOT` | No — gated on REM-020/021/022/023 and CAP ladder per the register |
| REMORA Enterprise | `LIMITED_ENFORCEMENT` / `PRODUCTION` | No — roadmap; requires externally verified decision engine |
| REMORA OEM / Embedded | (no profile declared) | No — by separate agreement only |

The declared profile is currently **`SHADOW_PILOT`**: shadow-mode operation on
real agent action logs; decisions, DecisionEnvelopes and counterfactual
deltas with **zero enforcement**. Any stage that enforces is not offered until
the corresponding register state exists; CI recomputes the profile from the
capability and remediation registers, so a stronger stage cannot be claimed by
editing this document.

## What the Shadow Pilot contains

- Shadow-mode governance of the customer's agent action stream via the
  `/v1/execution/assess` decision path (decision only, no dispatch).
- Atomically persisted per-tenant audit chain and DecisionEnvelope records.
- Counterfactual replay reports: what REMORA would have accepted, routed to
  review, or blocked, against ground truth where the customer can label it.
- An evidence pack for the go/no-go decision (see `SHADOW_PILOT.md`).

## Commercial terms skeleton

| Topic | Status |
|---|---|
| Licensor legal entity | Stian Skogbrott (see `LICENSE` / `legal/COMMERCIAL_LICENSE.md`) |
| License model | BUSL-1.1 source-available + commercial license |
| IP ownership | Licensor retains all IP; customer owns their data and evidence exports |
| Support entity | The licensor directly; no separate support organisation exists today |
| SLA availability | None offered at the Shadow Pilot stage (shadow mode has no availability dependency for the customer's agents) |
| DPA / subprocessors | Per engagement; see `DATA_HANDLING.md` |
| Data residency / retention / deletion / export | See `DATA_HANDLING.md` |
| Incident response | Best-effort at this stage; formal process is a Controlled Enforcement prerequisite |

Statements about capability maturity in customer-facing material must cite the
registers, not this document.
