# REMORA security overview (commercial)

Audience: customer security reviewers evaluating a Shadow Pilot. Canonical
technical sources: [`../08-security.md`](../08-security.md),
[`../assurance/threat_model_v1.md`](../assurance/threat_model_v1.md), and the
machine-readable registers under `docs/assurance/`. Where this summary and
those sources differ, the sources win.

## Trust boundaries

- **The agent is untrusted.** Every authoritative safety signal (risk tier,
  domain, action type, rollback capability) is derived server-side from the
  deployment-owned registry/ToolSpec; caller input can only downgrade trust,
  never raise it.
- **Deterministic hard guards carry the safety floor** — not model consensus.
  Research components (oracles, AROMER, disagreement diagnostics) are never
  prerequisites of the enforcing path
  (`../product/product_truth_contract.yaml`, CI-validated).
- **Approvals are independent.** The proposing credential can never approve
  its own action; human review identity is authenticated separately, and
  approvals are single-use, expiring, and bound to the exact call, ToolSpec
  and policy identity.
- **Fail closed.** Unknown context, malformed timestamps, missing
  configuration and unreachable dependencies refuse with machine-readable
  reasons; degradation is recorded, never silent.

## Evidence integrity

- Per-tenant SHA-256 hash-chained audit records (tamper-evident, not
  tamper-proof; signing key extends detection to whole-row rewrites).
- One-time execution grants with a durable consumed ledger and a high-water
  mark that makes ledger deletion evident.
- `UNKNOWN` execution outcomes are terminal and never auto-retried.

## Current-stage honesty

At `SHADOW_PILOT` nothing is enforced, so the pilot's security exposure is
read-path only: the mirrored action metadata the customer chooses to send.
The default MCP integration profile is `local` and sends nothing off the
machine; remote profiles require explicit opt-in (`DATA_HANDLING.md`).
No component is externally verified yet (`capability_register_v1.yaml` —
nothing is at `ENFORCED_PRODUCTION` or `EXTERNALLY_VERIFIED`). REMORA is not
production-certified and does not guarantee safety.
