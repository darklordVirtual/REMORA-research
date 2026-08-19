# REMORA documentation

This index separates the current execution architecture from research history. Start with the runtime boundary; use the research and archive sections only when you need the underlying experiments or historical record.

## Primary reading path

1. [README](../README.md) — project scope, evidence summary and current limitations.
2. [Developer handoff](../DEVELOPER_OVERVIEW.md) — shortest technical path through the repository.
3. [Architecture](../ARCHITECTURE.md) — canonical runtime architecture and module stability.
4. [Execution quickstart](deployment/execution-quickstart.md) — enforcing `/v1/execution/*` path.
5. [Evidence and claims](02-evidence-and-claims.md) — what each result establishes and what it does not.
6. [Security](08-security.md) — threat model and enforcement assumptions.
7. [Reproducibility](06-reproducibility.md) — benchmark and test reproduction.

For runtime questions, those documents take precedence over older design notes, research proposals and archived material.

## Runtime and integration

| Document | Purpose |
|---|---|
| [Architecture narrative](01-architecture.md) | Detailed pipeline and guard behavior; subordinate to `ARCHITECTURE.md` when the two differ |
| [API reference](07-api-reference.md) | REST surfaces and trust boundaries |
| [Execution lifecycle](execution-lifecycle.md) | Proposal-to-effect lifecycle and outbox behavior |
| [SDK](sdk.md) | Stable integration surface under `remora.sdk` |
| [CLI](cli.md) | Command reference |
| [MCP integration](integrations/mcp-integration.md) | MCP adapter notes |
| [Agent tool hook](integrations/agent_tool_hook.md) | Pre-tool-use integration |
| [Policy cookbook](policy_cookbook/README.md) | Policy examples |

`docs/reference_architecture.md` is retained as a compact overview, but `ARCHITECTURE.md` is the canonical architecture source.

## Evidence and assurance

| Source | Purpose |
|---|---|
| [Claim register](assurance/claim_register_v1.yaml) | Authoritative numerical claim registry |
| [Capability register](assurance/capability_register_v1.yaml) | Runtime wiring status by capability |
| [Release profiles](assurance/release_profiles_v1.yaml) | Deployment maturity profiles |
| [Release gates](assurance/release_gates.md) | Gate status per profile |
| [Remediation register](assurance/remediation_register.yaml) | Open assurance gaps |
| [Document register](assurance/document_register_v1.yaml) | Canonical / historical document status |
| [Assurance case](assurance/assurance_case_v1.md) | Structured assurance argument |
| [Metric definitions](assurance/metric_definitions_v1.md) | Canonical metric definitions |
| [Superseded claims](assurance/superseded_claims.md) | Claims replaced by later evidence |
| [Negative results](../NEGATIVE_RESULTS.md) | Failed hypotheses, regressions and limitations |

The capability and claim registers are the sources of truth for maturity and evidence. File presence, code volume or a merged implementation do not by themselves establish deployment maturity.

## Experiments and research

The current research material lives primarily under:

- `docs/research/` — active research questions, benchmark design and control mapping;
- `docs/benchmarks/` — benchmark methodology and statistical tests;
- `docs/experiments/` — experiment-specific records;
- `paper/` — publication material and derivations.

Useful entry points:

- [Experiments](03-experiments.md)
- [Negative results detail](04-negative-results-detail.md)
- [Related work](09-related-work.md)
- [Benchmark validation plan](11-benchmark-validation-plan.md)
- [AgentHarm validation](12-agentharm-validation.md)
- [Research control matrix](research/research_control_matrix.generated.md)
- [Research frontier roadmap](13-research-frontier-roadmap.md)

Research documents may describe proposals, diagnostics or hypotheses that are not wired into the execution path. Check the capability register before treating a research component as runtime functionality.

## Historical and superseded material

Anything under `docs/archive/` is historical unless a current canonical document explicitly references it as active evidence.

Older thermodynamic/statistical-physics work is retained for reproducibility and negative-result history. It is **not part of the primary execution architecture or evidence path**. The relevant files remain under `docs/thermodynamics/`, `docs/methods/`, `docs/claims/` and related use-case records because the repository preserves falsified and superseded research rather than deleting it.

Similarly, the original design documents for lifecycle/outbox and Signed ToolSpec are retained as design history:

- `docs/design/execution-lifecycle-outbox-v1.md`
- `docs/design/toolspec-signed-registry-v1.md`

Their old introductory status text is historical. Current implementation status is defined by the capability register, runtime code and tests, not by the original design snapshot.

## Documentation status rules

Use the following precedence when documents disagree:

1. machine-readable assurance registers;
2. `ARCHITECTURE.md` and current API/schema contracts;
3. current numbered documentation;
4. research proposals and design snapshots;
5. archived material.

Documentation changes should update or remove stale statements instead of adding another parallel explanation. New overview documents require a clear owner, audience and relationship to existing canonical material.

AI-assisted development is disclosed in [AI_USE.md](AI_USE.md). Documentation must still be concise, evidence-linked and free of unsupported promotional language.
