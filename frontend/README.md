# REMORA Frontend

This frontend is the interactive demonstration surface for REMORA. It is built as
a TanStack Start application and separates three concerns:

- **Simulation routes** show the governance model without external dependencies.
- **Live demo routes** call the committed Cloudflare Worker interfaces through
  typed client/server helpers.
- **Evidence and architecture routes** explain which claims are supported by
  tests, artifacts and limitations.

The frontend is a demonstrator for the control plane, not a production safety
certification. Critical actions shown in the UI are dry-run, simulated, gated or
routed through demo workers.

## Main Routes

| Route           | Purpose                                                                  | Execution mode           |
| --------------- | ------------------------------------------------------------------------ | ------------------------ |
| `/control-room` | Operator-style AI Action Firewall dashboard with escalation queue        | Deterministic simulation |
| `/cascade`      | Six-stage adaptive cascade with live model-backed stages when configured | Live/demo hybrid         |
| `/lab`          | Tool-call lab for RAG, law search and governed control-plane tools       | Live demo workers        |
| `/console`      | Session-oriented tool console with audit inspection                      | Live demo workers        |
| `/scenarios`    | Fixed enterprise scenarios for repeatable walkthroughs                   | Deterministic simulation |
| `/telemetry`    | Decision mix, latency, intercept and SLO view                            | Simulated telemetry      |
| `/policy`       | Nested governance and policy-as-code presentation                        | Static architecture      |
| `/evidence`     | Benchmark summary and limitations                                        | Static evidence          |
| `/architecture` | Runtime component map                                                    | Static architecture      |
| `/whitepaper`   | Web version of the technical position                                    | Static documentation     |

## Control Room Review Loop

The control-room route is the primary GUI demo for governed agentic action. It
shows REMORA as a review system that can move beyond approve/reject:

```text
PENDING_REVIEW -> SITE_VERIFICATION_PENDING -> EVIDENCE_RECEIVED
               -> READY_FOR_REVIEW -> APPROVED / REJECTED / CLOSED
```

The reviewer can request site verification when the evidence pack is not strong
enough to approve or reject safely. The demo then creates a deterministic
follow-up request with:

- reason flags,
- request type,
- priority and assignee,
- required evidence,
- similar-case history,
- policy-learning candidate,
- exportable `remora.review_envelope.v1` JSON.

This is intentionally modeled as a dry-run enterprise workflow. It demonstrates
the control-plane pattern for CMMS, field app, supervisor sign-off and audit
integrations without claiming that those external systems are connected in this
repository.

## Quality Gates

Run these before publishing frontend changes:

```bash
npm run lint
npm run build
```

`npm run lint` is configured with `--max-warnings=0`; warning noise is treated
as a quality failure. The repository CI also runs these commands from
`.github/workflows/quality-gates.yml`.

## Scaling Guidelines

- Keep reusable UI in `src/components`.
- Keep route-specific state and presentation in `src/routes`.
- Keep external interfaces in `src/lib/*.functions.ts`, `*.server.ts` or
  browser-safe `src/lib/*.ts` clients.
- Mark simulation data honestly in UI copy and route metadata.
- Do not expose control-plane secrets to the browser; use TanStack server
  functions for authenticated calls.
- Prefer deterministic simulation for demos that must be reproducible without
  live services.

## Claim Discipline

Use these terms precisely:

- "simulation" for deterministic local governance demonstrations.
- "live demo worker" for Cloudflare Worker calls used by this application.
- "production" only when a real production deployment has been independently
  configured and validated.

The frontend should make REMORA understandable, inspectable and commercially
credible without overstating what the benchmark artifacts prove.
