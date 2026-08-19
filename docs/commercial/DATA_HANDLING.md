# REMORA data handling

What data REMORA touches per deployment option, who holds it, and how it
leaves. Binding technical defaults are in code and tested; this document
summarizes them for commercial review.

## Data categories

| Category | Content | Where it lives |
|---|---|---|
| Action proposals | tool name, arguments, target environment, intent references | Customer-controlled REMORA instance |
| Decisions / envelopes | decision, reasons, hashes, policy identity | Per-tenant audit chain (customer's Postgres/SQLite) |
| Review records | approvals/rejections, reviewer principal, expiries | Same chain + review state |
| Evidence exports | lifecycle projections, chain verification, reports | Produced on demand; owned by the customer |
| Ground-truth labels | customer-provided labels for scoring | Customer's instance; used only for the pilot report |

## Defaults that protect the customer

- **Local by default.** The MCP integration profile defaults to `local`:
  zero outbound network, endpoint variables ignored, remote helpers refuse
  with machine-readable errors. `demo` requires explicit opt-in and prints a
  disclosure that content leaves the machine; `enterprise` requires explicit
  endpoints and fails startup when incomplete. No silent fallback exists.
  (Tested: `tests/test_mcp_privacy_profiles.py`.)
- **No downstream credentials in shadow mode.** The Shadow Pilot never holds
  credentials to the customer's systems of record; effect verification is an
  attestation by a named verifier on the customer's side.
- **Secrets masked.** Configuration secrets are never printed or written to
  artifacts (repository working agreement, CI secret guards).

## Residency, retention, deletion, export

In a customer-hosted deployment (the recommended option) all data above
resides in the customer's own infrastructure; residency and retention are
the customer's database policy. Deletion of audit-chain rows is detectable
by design (hash chain + consumed-grant high-water mark) — deletion is an
operator decision that leaves evidence, not a silent operation. Export:
evidence and lifecycle records are exportable via the API
(`/v1/execution/proposals/{id}/evidence`) and by direct database access.

For any engagement where the licensor processes customer data (demo
endpoints, hosted evaluation), a DPA and subprocessor list must be agreed
per engagement before data flows; none of the pilot's default paths require
it.
