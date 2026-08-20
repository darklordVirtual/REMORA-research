# REMORA deployment options

Options available at the current release profile (`SHADOW_PILOT`). All
enforcement-shaped deployment is out of scope until the register-gated stages
in `PRODUCT_PACKAGING.md` open.

## 1. Customer-hosted shadow deployment (recommended)

The REMORA execution API (`servers/`, Python/FastAPI) runs inside the
customer's environment. The agent action stream is mirrored to
`/v1/execution/assess`; nothing leaves the customer's boundary.

Requirements:

- Python 3.12+; install from the repository (BUSL-1.1 + commercial license).
- Durable state: `REMORA_PG_DSN` (Postgres, multi-node) or
  `REMORA_CHAIN_DB` (SQLite, single-node). Production mode refuses to start
  without one — a volatile audit chain and grant ledger is not a pilot.
- `REMORA_API_BEARER_TOKEN` and `REMORA_API_TOKENS` for authentication and
  tenant isolation, and `REMORA_CONTROL_PLANE_DSN` (or `_DB`) for the
  DecisionEnvelope store.
- **Two separate signing keys**, both required in production — the server
  refuses to start without either:
  - `REMORA_PDP_SIGNING_KEY` signs the PDP → PEP decision token, so the
    enforcement point can verify where an authorization came from.
  - `REMORA_ENVELOPE_SIGNING_KEY` signs each envelope's audit hash. Without
    it every audit record is written with `signature: null` and the chain is
    tamper-evident in name only.
- Deployment-owned ToolSpec registry for the inventoried tools.

## 2. Local evaluation (single machine)

`REMORA_MCP_PROFILE=local` (the default): full offline operation, zero
outbound network. Suitable for evaluating decisions on exported logs and for
the deterministic benchmark suite (`make benchmark`, no API keys).

## 3. Demo endpoints (evaluation only)

The public demo workers exist for evaluation and carry an explicit
disclosure: content sent to them leaves your environment. Never send
customer or sensitive data. Requires explicit opt-in
(`REMORA_MCP_PROFILE=demo`); there is no silent fallback to this option.

## Cloudflare edge components

The Cloudflare workers in `workers/` (agent-control ingress, research
workers) are part of the reference/edge architecture, classified in
`../product/product_truth_contract.yaml`. They are not required for a
customer-hosted shadow pilot. The single-authoritative-execution-path ADR
(`../architecture/ADR-single-authoritative-execution-path.md`) governs their
future role.
