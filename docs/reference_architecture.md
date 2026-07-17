# REMORA Reference Architecture — Policy-Governed Agent Assurance Control Plane

**Positioning statement:** REMORA is a reference architecture and executable
reference implementation for a policy-governed agent assurance control plane.
It is not an agent platform, not a data platform, and not a finished security
product. It defines — and implements, at research grade — the layer that sits
*between* an agent platform and the systems agents act on.

**Maturity:** research-grade, `SHADOW_ONLY`. See
[Scope and maturity](#8-scope-and-maturity) and
[docs/assurance/release_gates.md](assurance/release_gates.md) before relying
on any component. This document describes what the reference implementation
does today, with pointers to the exact modules and tests; it makes no claim
beyond them.

---

## 1. The problem this layer solves

Agent platforms answer *how agents reason and act*. Enterprise operators of
agent fleets must additionally answer, before any action reaches a real
system:

1. **Authorization on the execution path** — is *this* action, with *these*
   arguments, in *this* environment, permitted right now? Per-tool access
   control is insufficient: each step can be individually permitted while the
   combination is not.
2. **Uncertainty-aware autonomy** — how confident is the system, and does
   that confidence level justify autonomous execution, or does it require
   verification, abstention, or a human?
3. **Delegated authority** — which capabilities were actually delegated to
   the acting agent, by whom, and can that be verified at request time —
   including when the requester is another organisation's agent?
4. **Evidence and accountability** — when the action is later disputed, can
   the operator replay the exact policy, evidence, and decision path that
   authorized it?

REMORA's answer is a control plane with four planes: **decision** (policy +
uncertainty), **enforcement** (signed authorization, fail-closed),
**identity/delegation** (who may ask for what), and **evidence** (signed,
replayable audit). Each plane is independently implemented and testable.

---

## 2. Architecture overview

```text
            Agent platform / orchestrator / external counterparty agent
                                    │
                          proposed action (tool call)
                                    │
        ┌───────────────────────────▼────────────────────────────┐
        │              REMORA ASSURANCE CONTROL PLANE            │
        │                                                        │
        │  1. Identity & delegation      A2AGovernanceEnvelope   │
        │     — who is asking, on whose  remora/governance/      │
        │       authority, within what     a2a_envelope.py       │
        │       attenuated scope                                 │
        │                                                        │
        │  2. Observation binding        PolicyObservation +     │
        │     — canonical hash binds the   canonical_tool_call_  │
        │       decision to full args      hash (TOCTOU-safe)    │
        │                                                        │
        │  3. Policy decision point      RemoraDecisionEngine    │
        │     — hard guards first, then  (or OPA/Rego via        │
        │       uncertainty routing:       OPAAdapter, floored   │
        │       ACCEPT / VERIFY /          by hard_guard_floor)  │
        │       ABSTAIN / ESCALATE                               │
        │                                                        │
        │  4. Evidence evaluation        evidence fields,        │
        │     — contradiction blocks,      claim-graph topology, │
        │       provenance recorded        counterfactual gate   │
        │                                                        │
        │  5. Enforcement point          PolicyDecisionToken +   │
        │     — signed PDP→PEP token,      EnforcementGate       │
        │       fail-closed on tamper    remora/enforcement/     │
        │                                                        │
        │  6. Human escalation           VERIFY/ESCALATE carry   │
        │     — review requirements are    human_review_required │
        │       policy outputs, not        + full reason codes   │
        │       conventions                                      │
        │                                                        │
        │  7. Decision envelope          DecisionEnvelope        │
        │     — signed, versioned,       remora/governance/      │
        │       hash-chained record        envelope.py           │
        │                                                        │
        │  8. Telemetry & audit graph    OTel GenAI semconv +    │
        │     — gen_ai.* + remora.*        remora.* attributes;  │
        │       spans; RDF export for      hash-chained audit;   │
        │       graph-native audit         SPARQL-queryable      │
        └───────────────────────────┬────────────────────────────┘
                                    │
                     ACCEPT │ VERIFY │ ABSTAIN │ ESCALATE
                                    │
            Business systems / APIs / workflow engines / OT-safe
            integration gateways  (execution happens HERE, never
            inside the control plane)
```

Two properties hold across all eight elements:

- **Fail-closed everywhere.** Missing signals degrade the decision toward
  review, never toward execution: unknown risk tier → VERIFY, unvalidated
  schema on a mutating call → VERIFY, unreachable policy daemon on
  high/critical risk → VERIFY/ESCALATE, unsigned tokens or envelopes →
  refused.
- **Decision monotonicity.** No adapter, fallback, or external policy can
  downgrade a verdict below the engine's hard-guard floor
  (`remora.policy.decision_engine.hard_guard_floor`). This holds for the
  Python engine (REM-003 mutation tests), the OPA path
  (`tests/test_opa_parity.py`), and delegation chains (scope can only be
  attenuated, `tests/test_a2a_envelope.py`).

---

## 3. The decision plane

`remora/policy/decision_engine.py` maps a `PolicyObservation` (the immutable
snapshot of one proposed action and its governance context) to a
`DecisionReport` with one of four actions:

| Action | Meaning | Human involved |
|---|---|---|
| `ACCEPT` | Execute autonomously | No |
| `VERIFY` | Execute only after human review | Yes, before execution |
| `ABSTAIN` | Do not execute; insufficient/contradicting basis | No (nothing executes) |
| `ESCALATE` | Hard stop; route to human with full context | Yes, unconditionally |

Evaluation order is safety-first:

1. **Hard guards** (`hard_guard_floor`): adversarial input, schema-invalid
   calls, forbidden tools, coercion/blackmail patterns, failed
   counterfactuals, contradicting evidence, tainted arguments. Unconditional;
   no trust score overrides them.
2. **Conditional risk gates**: critical phase + critical risk, missing
   rollback on high risk, uncertain state transitions, the
   production-write matrix, oracle-quorum, minimax/trap gates.
3. **Uncertainty routing**: only after every guard passes does calibrated
   trust routing decide between ACCEPT and the conservative actions.

Every decision carries machine-readable `reasons` (a stable enum), an
`explain()` rule trace, and the policy version. The 28 REM-017 mutation
tests assert that removing any single guard breaks a named test.

### Autonomy levels as policy, not convention

The four actions define the autonomy boundary per action, not per agent: the
same agent can be autonomous on telemetry reads, review-gated on work-order
proposals, and hard-blocked on actuation — in one policy evaluation pass.
`scripts/demo_industrial_maintenance.py` demonstrates exactly this boundary
against the real engine, pinned by `tests/test_demo_industrial_maintenance.py`.

---

## 4. Policy-as-code plane (OPA/Rego)

For multi-team governance, the decision plane can delegate to an
[Open Policy Agent](https://www.openpolicyagent.org/) daemon
(`remora/policy/opa_adapter.py`), giving governance teams GitOps-versioned
Rego policy without redeploying application code.

Three mechanisms keep this delegation safe:

1. **Full-contract export.** `OPAContext` exports every observation field the
   decision path reads — including all security hard-block signals — enforced
   structurally by `tests/test_opa_parity.py` (the test scans the engine
   source for field accesses; a new guard on an unexported field fails CI).
2. **Runtime monotonicity floor, in two tiers.** Every OPA result is floored
   by `hard_guard_floor()` (all risk tiers) — and on high/critical risk the
   *entire* Python decision, including conditional gates like the
   production-write matrix and missing-rollback checks, is a monotone floor.
   An external policy can therefore only relax decisions in the low/medium
   band; it can only tighten high/critical ones. Overrides are recorded in
   the report (`source_of_decision="opa_hard_guard_floor"` /
   `"opa_engine_floor"`).
3. **Golden conformance, mandatory in CI.** `scripts/opa_conformance.py`
   evaluates a deterministic observation set through both engines via
   `opa eval` and fails on hard-guard divergence. CI installs a pinned OPA
   version and runs this as a hard gate on every push (`.github/workflows/
   ci.yml`, job `opa-conformance`); `--strict` mode proves full equivalence
   for deployments that maintain a complete Rego port.

Outage behavior is fail-closed by risk tier: unreachable OPA on
high/critical risk yields VERIFY/ESCALATE, never silent fallback to ACCEPT.

---

## 5. Identity and delegation plane (A2A)

Agent-to-agent protocols standardise transport; they do not decide whether a
counterparty agent should be trusted. `remora/governance/a2a_envelope.py`
defines the signed governance envelope REMORA expects alongside any
cross-boundary agent request:

- **Identity + accountability**: agent id/version, issuing organisation, and
  the organisation *accountable* for the agent — verification fails closed
  without accountability.
- **Delegation chain with capability attenuation and per-link attestation**:
  each link may only narrow the scope it received (strict subset semantics;
  wildcards rejected) and carries its own signature and key id (`kid`)
  verified against a key registry — the envelope issuer alone cannot
  fabricate the delegation history, and removing a key from the registry
  revokes every dependent chain. The requested action must fall inside the
  final attenuated scope.
- **Audience, replay, and argument binding**: a mandatory audience (the
  intended verifier), a per-envelope nonce checked via a caller-supplied
  replay guard, and an optional binding to the canonical tool-call hash —
  the same envelope cannot authorise a different verifier, a replayed
  request, or a different argument payload.
- **Policy + evidence binding**: the policy version evaluated and
  content-addressed evidence references, so cross-organisation disputes can
  be replayed against the exact artifacts.
- **Integrity**: HMAC-SHA256 over canonical serialisation, same discipline as
  the PDP→PEP token; every verification failure is reported (complete defect
  set, not first-failure), and malformed input — bad timestamps, bad JSON —
  is a failure code, never an exception or a pass. The symmetric-key layer
  is a stated reference-implementation scope; the module documents the
  asymmetric (JWS + published keys + rotation) production path.

This is the request-side complement to the decision plane: delegation answers
*may this agent ask*; the decision engine answers *should this action run*.

---

## 6. Evidence and audit plane

- **DecisionEnvelope** (`remora/governance/envelope.py`): the canonical,
  signed, versioned governance record per decision — kept contract-stable
  (`schemas/decision_envelope_schema.yaml`).
- **Hash-chained audit** (`remora/governance/audit_chain.py`): tamper-evident
  (not tamper-proof — see Limitations) decision history.
- **Graph export**: audit records export to RDF/N-Triples with per-tenant URI
  namespaces, SPARQL-queryable — `agent → decision → outcome` joins the
  operator's knowledge-graph tooling instead of living in a proprietary log
  format.
- **Enforcement binding**: `canonical_tool_call_hash` binds decisions to the
  *full* argument payload; the enforcement gate recomputes it immediately
  before execution and refuses on mismatch (TOCTOU protection).

---

## 7. Telemetry plane (OpenTelemetry)

`remora/observability/otel.py` emits spans per governed action with two
attribute families:

- **`gen_ai.*`** — OTel GenAI semantic conventions
  (`gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.tool.call.id`,
  `gen_ai.agent.id`, `gen_ai.conversation.id`), so REMORA spans correlate
  with any other GenAI-instrumented component in the same distributed trace
  without custom configuration.
- **`remora.*`** — governance signals with no semconv equivalent (phase,
  entropy, dissensus, decision, policy version, decision source,
  human-review flag).

Prompts are never exported to telemetry (length only). `gen_ai.tool.call.id`
is a unique per-invocation id (replays of identical calls stay distinct);
the deterministic canonical argument hash is emitted as
`remora.tool_call_hash`, and `remora.decision_envelope.id` links the span to
the evidentiary record. Spans are created against a pinned OTel schema URL
so attribute interpretation is versioned. Traces are the operational view;
the DecisionEnvelope remains the evidence.

---

## 8. Scope and maturity

Stated plainly, because a reference architecture is only useful when its
boundaries are explicit:

- **Deployment status is `SHADOW_ONLY`.** The intended first deployment mode
  is shadow: REMORA consumes real agent action logs and produces decisions,
  envelopes, and counterfactual deltas (`make shadow-replay`) *without*
  enforcement, until the release gates close. Production gates and their
  current state: [docs/assurance/release_gates.md](assurance/release_gates.md).
- **Benchmarks are internal.** Safety results (including the external-dataset
  benchmark) were run by the author; independent replication is a tracked,
  unmet evidence level. No field deployment data exists.
- **The adaptive calibration layer is experimental.** The closed-loop
  learning component (AROMER) is research work layered on top of this
  architecture; nothing in this document depends on it, and its metrics are
  not evidence for the control plane.
- **Tamper-evident, not tamper-proof.** The audit chain detects modification;
  preventing it requires external WORM storage, out of scope here.
- **Integration adapters are reference-grade.** The OPA, OTel, RDF, and MCP
  integrations are working reference implementations with tests — not
  hardened connectors for any specific enterprise data platform, workflow
  system, or OT gateway. Site adapters are deliberately thin: the contract
  surface (`PolicyObservation` in, `DecisionEnvelope` out) is the stable part.

Full inventory of caveats and negative results:
[NEGATIVE_RESULTS.md](../NEGATIVE_RESULTS.md),
[README — Limitations](../README.md#limitations).

---

## 9. Standards mapping

| Concern | Standard | REMORA component |
|---|---|---|
| Policy-as-code | OPA / Rego | `OPAAdapter` + conformance harness |
| Agent telemetry | OpenTelemetry GenAI semantic conventions | `remora/observability/otel.py` |
| Tool connectivity | MCP (Model Context Protocol) | policy-gated MCP server (`remora` MCP tools) |
| Agent-to-agent requests | A2A-style protocols | `A2AGovernanceEnvelope` (governance side-channel) |
| Audit interchange | RDF / N-Triples / SPARQL | audit graph exporter |
| Decision record | JSON Schema | `schemas/decision_envelope_schema.yaml` |

The control plane holds no opinion about which agent framework, model
vendor, or data platform sits above or below it — every integration point is
one of these open contracts.

---

## 10. Adoption path (shadow-first)

1. **Weeks 0–4 — Shadow.** Feed real agent action logs through
   `scripts/shadow_replay.py`. Output: counterfactual governance deltas
   (what would have been blocked/reviewed), calibration data, and a concrete
   friction estimate — with zero impact on the running system.
2. **Weeks 4–8 — Policy fitting.** Encode the operator's actual autonomy
   rules (risk tiers, forbidden capabilities, environment matrices) as
   Rego + engine configuration; validate with the conformance harness and
   the operator's own replayed logs.
3. **Weeks 8–12 — Gated enforcement.** Enforce on one low-consequence,
   high-volume action class first (e.g. recommendation writes), with the
   documented mode-degradation path (full governance → hard-blocks-only)
   and independent review of the deployment (the REM-021 gate) as the
   promotion criterion.

Each phase produces artifacts (decision envelopes, replay reports, conformance
results) that the next phase's go/no-go decision is made against — the same
evidence discipline this repository applies to itself.
