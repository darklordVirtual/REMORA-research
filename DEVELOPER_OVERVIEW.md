# REMORA developer handoff

This is the shortest technical path through the repository for a new developer or external reviewer.

REMORA is a **policy-gated execution assurance layer for operational AI agents**. An agent proposes a tool call; REMORA decides whether that exact call may proceed, may proceed only after verification, must stop, or must be escalated. The enforcement path then binds any authorization to the exact call and records the lifecycle.

The repository also contains experiments, benchmark harnesses, optional integrations, historical research paths and AROMER. Those are valuable, but they are **not prerequisites for understanding the execution kernel**.

## 1. The golden path

```text
Agent / planner
    |
    | proposed tool name + exact arguments + target + intent reference
    v
Authoritative context boundary
    |-- deployment-owned ToolSpec
    |-- deployment-owned tool metadata
    |-- system-of-record state / approved intent
    v
PolicyObservation
    v
RemoraDecisionEngine
    |
    |-- ACCEPT
    |-- VERIFY
    |-- ABSTAIN
    `-- ESCALATE
          |
          v
Review / fresh re-gate where required
          v
single-use policy grant
          v
PEP -> ExecutionLease -> GovernedToolDispatcher
          v
outbox lifecycle / downstream side effect
          v
effect verification
          v
tenant audit chain + proposal lifecycle
```

The execution API is the enforcing surface: `POST /v1/execution/*`.
The library call `assess_tool_call(...)` is useful for local reasoning and integration tests, but it is advisory unless the caller routes execution through the enforcing path.

## 2. What is core, optional, experimental and legacy

### CORE — understand these first

These modules form the current assurance/execution kernel:

| Concern | Primary implementation |
|---|---|
| Policy decision | `remora/policy/decision_engine.py` |
| Authoritative observation | `remora/policy/observation.py` |
| Tool authority / metadata | `remora/toolcall/deployment_registry.py` |
| Signed ToolSpec | `remora/toolcall/toolspec.py` |
| PDP -> PEP grant | `remora/enforcement/token.py`, `remora/enforcement/gate.py` |
| Lease-bound dispatch | `remora/enforcement/lease.py` |
| Crash-consistent dispatch intent | `remora/enforcement/outbox.py` |
| Review / TTL / re-gate | `remora/governance/review_queue.py` |
| Lifecycle model | `remora/governance/lifecycle.py` |
| Tenant audit chain | `remora/governance/tenant_chain.py` |
| Effect verification | `remora/governance/effect_verification.py` |
| HTTP execution surface | `servers/execution_api.py` |

If a reviewer has only 30 minutes, read those files in that order and then run the tests listed below.

### OPTIONAL — useful extensions, not required to understand the kernel

- OPA/Rego delegation.
- semantic bundles and deployment-owned intent resolvers.
- A2A delegation envelopes.
- OTel helpers.
- oracle-backed `/v1/assess` research surface.
- MCP and integration adapters.

Optional modules may strengthen context, interoperability or observability, but the deterministic hard-guard floor must not depend on them being available.

### EXPERIMENTAL — research, never treat as production evidence

- AROMER learning/adaptation loops.
- calibration experiments and selective-prediction research.
- multi-oracle aggregation experiments.
- benchmark-specific routing experiments.
- research-frontier work packages.

The repository intentionally keeps negative results and superseded claims. Presence in the tree is not the same thing as promotion into the execution path.

### LEGACY / HISTORICAL

Anything under `docs/archive/legacy/` is historical unless a current document explicitly says otherwise. Historical experiments may remain reproducible, but they must not be used to infer current runtime behavior.

## 3. Runtime profiles for handoff and pilot work

`REMORA_RUNTIME_PROFILE` makes the intended trust level explicit:

| Profile | Intended use | Signed ToolSpec | Durable execution state |
|---|---|---:|---:|
| `development` | local development and unit tests | optional | optional |
| `research` | benchmark / shadow work | optional, degradation recorded | optional |
| `review` | external technical review / integration handoff | **required** | **required** |
| `controlled_pilot` | bounded partner pilot | **required** | **required** |

For `review` and `controlled_pilot`, REMORA refuses execution-path metadata resolution unless a signed ToolSpec bundle and durable execution state are configured. This prevents a reviewer or pilot from accidentally exercising the weaker legacy path while believing they are testing the strongest architecture.

The strict path should normally include:

```bash
export REMORA_RUNTIME_PROFILE=review
export REMORA_ENABLED_SURFACES=execution
export REMORA_TOOLSPEC_BUNDLE=/run/remora/toolspec-bundle.json
export REMORA_TOOLSPEC_SIGNING_KEY=...
export REMORA_TOOLSPEC_TRUSTED_IDENTITIES=release-signer-v1
export REMORA_PG_DSN='postgresql://...'
# or REMORA_CHAIN_DB=/var/lib/remora/execution.db for a single-node review
```

See `docs/deployment/execution-quickstart.md` for the complete setup.

## 4. The five questions a reviewer should be able to answer

1. **Who declares what a tool means?**  The deployment, through a signed ToolSpec / trusted metadata source — never the calling agent.
2. **Can model confidence override a hard safety rule?**  No. Deterministic hard guards have precedence.
3. **Is authorization bound to the exact action?**  Yes. The proposal/tool-call identity flows into the grant/lease and is rechecked before dispatch.
4. **What happens if the process crashes around a side effect?**  The outbox lifecycle records dispatch intent and distinguishes pending, dispatching, success, failure, refusal and unknown outcomes; unknown is not silently retried.
5. **Can REMORA stop an agent that has another credential path around it?**  No. Enforcement only holds when the governed dispatcher is the authority path to the protected tool.

## 5. Reproduce the core before reading the research history

```bash
python -m pip install -e '.[dev]'
python -m remora try
python -m pytest tests/test_toolspec_execution_wiring.py -q
python -m pytest tests/test_execution_outbox_wiring.py -q
python -m pytest tests/test_token_hardening.py -q
python -m pytest tests/test_runtime_profile.py -q
python -m pytest tests/test_execution_api.py -q
```

Then run the deterministic full suite:

```bash
python -m pytest tests/ -q
```

For a deployment-shaped test, use `deploy/ot-pilot/` or the execution quickstart rather than constructing your own path from individual research modules.

## 6. Evidence and claims

Do not infer maturity from code volume. Use these machine-governed sources:

- `docs/assurance/capability_register_v1.yaml` — how deeply each capability is wired.
- `docs/assurance/claim_register_v1.yaml` — what each numerical claim actually establishes.
- `docs/02-evidence-and-claims.md` — reviewer-readable claim/caveat map.
- `NEGATIVE_RESULTS.md` — failed hypotheses and superseded directions.

The caveat is part of the claim. A benchmark result is not field validation, and an implemented library component is not automatically part of the enforcing API path.

## 7. Current boundaries

REMORA is still research/shadow-mode software, not a certified production safety system. In particular:

- external replication remains separate from internal reproducibility;
- the dispatcher must front the real downstream authority for enforcement to be meaningful;
- deployment-specific identity, credential and operational controls remain the deployer's responsibility;
- optional and experimental modules must not be presented as proven kernel capability unless the capability register says they are wired;
- `servers/execution_api.py` is still a large orchestration module. Its staged split into wire contracts, service orchestration, persistence, dispatch and lifecycle projection is tracked in **#241**; do not interpret module size as an intentional long-term architecture.

## 8. Repository reading order

A reviewer should normally follow this sequence:

1. `README.md`
2. **this file**
3. `ARCHITECTURE.md`
4. `docs/deployment/execution-quickstart.md`
5. the CORE files in section 2
6. `docs/02-evidence-and-claims.md`
7. only then: experiments, paper, AROMER and research-frontier material

That order is deliberate: evaluate the executable trust boundary first, then evaluate the research claims around it.
