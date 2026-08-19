# REMORA developer handoff

Use this file to orient a new developer or external reviewer. Runtime behavior is defined by code, schemas and assurance registers; research files do not implicitly define the execution path.

## Runtime path

```text
Agent / planner
    |
    | proposed tool + exact arguments + target + intent reference
    v
Deployment-owned context
    |-- Signed ToolSpec / tool metadata
    |-- system-of-record state
    |-- approved intent / authority
    v
PolicyObservation
    v
RemoraDecisionEngine
    |-- ACCEPT
    |-- VERIFY
    |-- ABSTAIN
    `-- ESCALATE
          |
          v
review / re-gate when required
          v
single-use policy grant
          v
PEP -> ExecutionLease -> GovernedToolDispatcher
          v
outbox state -> downstream effect
          v
effect verification -> tenant audit chain
```

`POST /v1/execution/*` is the enforcing surface. `assess_tool_call(...)` is advisory unless downstream execution is forced through the governed dispatcher.

## Core modules

| Concern | Implementation |
|---|---|
| Policy decision | `remora/policy/decision_engine.py` |
| Policy observation | `remora/policy/observation.py` |
| Deployment tool authority | `remora/toolcall/deployment_registry.py` |
| Signed ToolSpec | `remora/toolcall/toolspec.py` |
| PDP→PEP grant | `remora/enforcement/token.py`, `remora/enforcement/gate.py` |
| Execution lease | `remora/enforcement/lease.py` |
| Dispatch/outbox | `remora/enforcement/outbox.py` |
| Review and re-gate | `remora/governance/review_queue.py` |
| Lifecycle | `remora/governance/lifecycle.py` |
| Audit | `remora/governance/tenant_chain.py` |
| Effect verification | `remora/governance/effect_verification.py` |
| HTTP execution surface | `servers/execution_api.py` (routes + orchestration) |
| Wire contracts | `servers/execution_contracts.py` (Pydantic request/response models) |
| Review-state persistence | `remora/persistence/execution_state.py` (all-or-nothing transaction adapter) |
| ToolSpec authorization context | `remora/execution/authorization.py` (bundle verify, assessed-record read-back) |
| Legal citation existence | `remora/legal/citation_existence.py` (authoritative-registry fact; model output is advisory only) |

Read those before the research modules.

## Stability boundary

### Core

The modules above form the current execution/assurance kernel. Their maturity is still bounded by the capability register; “core” does not mean externally verified or production certified. The per-capability classification is machine-checked against `docs/product/product_truth_contract.yaml` by `scripts/check_product_truth.py`.

### Optional

- OPA/Rego delegation
- semantic bundles and intent resolvers
- A2A delegation envelopes
- OTel helpers
- MCP/integration adapters
- oracle-backed `/v1/assess` research surface

Optional components may add context or interoperability. They must not weaken deterministic hard guards.

### Experimental / research

- AROMER adaptation loops
- calibration and selective-prediction experiments
- multi-oracle aggregation
- benchmark-specific routing work
- research-frontier work packages
- older thermodynamic/statistical-physics hypotheses and diagnostics

These are research material, not evidence that the corresponding mechanism is active in the enforcing runtime.

### Historical

`docs/archive/` is historical unless a current canonical document explicitly references an item as active evidence. Original design snapshots under `docs/design/` may also describe pre-implementation state; use the capability register and current code for implementation status.

## Runtime profiles

| Profile | Use | Signed ToolSpec | Durable state |
|---|---|---:|---:|
| `development` | local development/tests | optional | optional |
| `research` | benchmark/shadow work | optional; degradation recorded | optional |
| `review` | external technical review | required | required |
| `controlled_pilot` | bounded pilot | required | required |

`review` and `controlled_pilot` fail closed when required ToolSpec, signer, registry, state or PDP-signing prerequisites are absent. `controlled_pilot` also requires production environment mode.

See `docs/deployment/execution-quickstart.md` for configuration.

## Review questions

A reviewer should be able to answer these from code and tests:

1. Who defines tool meaning and authority? — The deployment, not the agent.
2. Can model confidence override a hard guard? — No.
3. Is authorization bound to the exact action? — Yes; proposal/call identity is rechecked before dispatch.
4. What happens around a crash? — The outbox records dispatch state; unknown outcomes are not silently treated as success or retried as if nothing happened.
5. Can REMORA enforce against a bypass credential path? — No; the governed dispatcher must be the authority path to the protected tool.

## Reproduce the execution core

```bash
python -m pip install -e '.[dev]'
python -m remora try
python -m pytest tests/test_runtime_profile.py -q
python -m pytest tests/test_toolspec_execution_wiring.py -q
python -m pytest tests/test_execution_outbox_wiring.py -q
python -m pytest tests/test_token_hardening.py -q
python -m pytest tests/test_execution_api.py -q
python -m pytest tests/ -q
```

Use `deploy/ot-pilot/` or the execution quickstart for a deployment-shaped test.

## Evidence sources

Do not infer maturity from implementation size. Use:

- `docs/assurance/capability_register_v1.yaml` — runtime wiring depth;
- `docs/product/product_truth_contract.yaml` — capability classes (core/optional/experimental/legacy/demo), CI-checked against public copy;
- `docs/architecture/ADR-single-authoritative-execution-path.md` — one authoritative execution path; edge workers are ingress;
- `docs/commercial/PRODUCT_PACKAGING.md` — what is commercially offered (Shadow Pilot), bound to release profiles;
- `docs/assurance/claim_register_v1.yaml` — governed numerical claims;
- `docs/02-evidence-and-claims.md` — reviewer-readable evidence boundaries;
- `NEGATIVE_RESULTS.md` — failed and superseded hypotheses.

A benchmark result is not field validation. A library implementation is not automatically wired to the execution API. Internal reproducibility is not external replication.

## Known boundary

`servers/execution_api.py` is being decomposed by responsibility (issue #241). Extracted so far, each characterized against a byte-identical OpenAPI schema: wire contracts (`servers/execution_contracts.py`), the review-state transaction adapter (`remora/persistence/execution_state.py`) and the ToolSpec authorization context (`remora/execution/authorization.py`). Remaining: service orchestration, dispatch and lifecycle projection. Refactoring must preserve wire contracts, policy semantics, transaction boundaries and audit history.

## Reading order

1. `README.md`
2. `DEVELOPER_OVERVIEW.md`
3. `ARCHITECTURE.md`
4. `docs/deployment/execution-quickstart.md`
5. core modules above
6. `docs/02-evidence-and-claims.md`
7. research, experiments and paper material as needed
