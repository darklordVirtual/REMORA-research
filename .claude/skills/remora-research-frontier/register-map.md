# Register snapshot (read 2026-10-04, master `fea7928`)

A scan aid only. The YAML files are authoritative and may have moved on;
re-grep before quoting a status. Lines below carry no numbers that may be
cited; numbers live in the claim register.

## Research control matrix, RES (docs/research/research_control_matrix_v1.yaml)

| ID | Line | Maturity |
|---|---|---|
| RES-001 | Causal post-hoc explainability and concept interventions | library_only |
| RES-002 | Selective prediction and abstention | implemented_and_tested |
| RES-003 | CRC-inspired weighted empirical selective routing (`crc.py`) | empirically_evaluated_adaptation |
| RES-004a | Multi-oracle consensus and aggregation | implemented_and_tested |
| RES-004b | LLM-as-judge cross-model verification | implemented_and_tested |
| RES-005 | Tool-use safety and agent guardrails | implemented_and_tested |
| RES-006 | Evidence grounding and retrieval-augmented verification | implemented_and_tested |
| RES-007 | Statistical-physics control signals (entropy, phase, Lyapunov) | library_only (framing withdrawn, NR §38) |
| RES-008 | Nested learning, context flow, continuum memory | conceptual_translation_implemented |
| RES-009 | Enterprise AI governance and audit | reference_design |
| RES-010 | Anytime-valid confidence sequences | library_only |
| RES-011 | SDAD-inspired content-bound specification intake | conceptual_translation_implemented |
| RES-012 | Task-bound execution authority and non-decaying loop state | implemented_and_tested |
| RES-013 | Observed runtime surface, authority paths, recheckable effect evidence | implemented_and_tested |
| RES-014 | Evidence completeness against claim contracts | implemented_and_tested |
| RES-015 | Closed-world resolved-effect binding | implemented_and_tested |
| RES-016 | Dependency-scoped plan validity (PlanFence → PlanBinding) | implemented_and_tested |
| RES-017 | Evidence captured outside the agent's process | implemented_and_tested |
| RES-018 | Procedure obligations and derived completion (`procedure.py`) | implemented_and_tested; general temporal logic and assume-guarantee composition explicitly not implemented |
| RES-019 | Measured correctness of the enforcement gate itself | empirically_evaluated_adaptation |
| RES-020 | Capability minimization before reasoning, enforced through execution and effect | implemented_and_tested |
| RES-021 | Test adequacy of the evidence-sufficiency corpus (mutation, metamorphic, generated) | library_only |

Bibliography roles in the same file: `implemented_line` entries name code;
`positioning_only` entries are framing. `code_citations` lists every arXiv id
cited inside a module, including two "deliberately not implemented" citations
(learned post-state prediction 2506.02918) that must stay that way.

## Research shelf, SHELF (docs/research/research_shelf_v1.yaml)

| ID | Component | Adoption | RF |
|---|---|---|---|
| 001 | Declarative tool capability/effect contracts (ToolGuardian) | ADOPTED | RF-10 |
| 002 | Predict declared state change before execution | ADOPTED | RF-10 |
| 003 | Task alignment checked at every step (Task Shield) | PARTIAL | RF-10 |
| 004 | Plan as tool dependency graph (IPIGuard) | UNEVALUATED | RF-10 |
| 005 | Verify-before-commit (VIGIL) | UNEVALUATED | RF-10 |
| 006 | Persistent safety state across trajectory (MAGE) | UNEVALUATED | RF-10 |
| 007 | Per-value integrity/confidentiality labels (Fides IFC) | UNEVALUATED | RF-02 |
| 008 | Capabilities bound to data (CaMeL) | UNEVALUATED | RF-02 |
| 009 | Programmable fine-grained privilege (Progent) | UNEVALUATED | RF-10 |
| 010 | Over-privileged tool selection benchmark | UNEVALUATED | RF-09 |
| 011 | Paired act/abstain benchmark (AgentAbstain) | SCOPED | RF-09 |
| 012 | Temporal ordering constraints (Agent-C) | PARTIAL | RF-10 |
| 013 | Minimal causal tool frontier | SCOPED | RF-10 |
| 014 | Kernel Language Entropy backend | PROTOTYPE_ONLY | RF-06 |
| 015 | Semantic entropy probes | PROTOTYPE_ONLY | RF-06 |
| 020 | Wire routing context builder into authoritative path (internal) | PARTIAL | RF-10 |
| 021 | Postcondition observation after governed effect (internal) | SCOPED | RF-10 |
| 022 | Adversarial filesystem/shell corpus (internal) | UNEVALUATED | RF-10 |
| 023 | Derivation receipts for derived argument values (internal) | ADOPTED | RF-10 |
| 024 | Programmatic Tool Calling as composition layer | SCOPED | RF-11 |
| 025 | Content-bound context intake, Spec Fidelity (SDAD) | PARTIAL | none |
| 026 | Interoperable per-decision evidence record (AIREP) | PARTIAL | RF-10 |
| 027 | Authorization revalidated at provider commit (AID-Guard) | UNEVALUATED | RF-10 |
| 028 | Independent runtime witness (HANSARD) | UNEVALUATED | RF-10 |
| 029 | Measured correctness of the gate (task-state influence) | ADOPTED | none |
| 030 | Trace capture outside agent control (trace tampering) | PARTIAL | RF-08 |
| 031 | Non-decaying loop safety state (Safety Does Not Compose) | ADOPTED | none |
| 032 | Dependency-scoped plan validity (Fresh Memory, Stale Plans) | ADOPTED | none |
| 033 | Closed-world resolution of tool identity | ADOPTED | RF-01 |
| 034 | Permission-aware MCP discovery (zero-trust MCP) | UNEVALUATED | RF-01 |
| 035 | Query-active procedural obligations (ContractEval) | PARTIAL | RF-03 |
| 036 | Assume-guarantee temporal contracts | PARTIAL | RF-03 |
| 037 | Completion claims checked against obligations (overclaiming) | PARTIAL | none |
| 038 | Typed verification status across handoffs | UNEVALUATED | none |
| 039 | Cut-point replay of recorded incidents (Chronicle) | UNEVALUATED | none |
| 040 | Failure-informed runtime policies (FIRE) | UNEVALUATED | none |
| 041 | Per-argument provenance through multi-turn tool use (SAP) | UNEVALUATED | RF-02 |

## Frontier roadmap, RF (docs/13-research-frontier-roadmap.md)

| ID | Work package | Tag | Priority as written |
|---|---|---|---|
| RF-01 | Tool-registry integrity (tool poisoning) | gating | P1, S |
| RF-02 | Argument provenance / capability labels (CaMeL-class IFC) | gating+evidence | P1 slice 1, P2 full |
| RF-03 | Policy DSL with formal semantics + trajectory invariants | gating | P3 |
| RF-04 | VERIFY resolution via AI-control protocols (the FBR fix) | routing/escalate | P0; slice 1 = library-only `control_protocols.py`; NR §19 bounds it |
| RF-05 | Drift-aware conformal + anytime-valid monitoring | routing | P3 (selector falsified by SAP v3 first) |
| RF-06 | Semantic-entropy backend parity + CWV | uncertainty | P0 |
| RF-07 | Evidence sufficiency + adversarial corpus robustness | evidence/RAG | P2 |
| RF-08 | Audit anchoring: Merkle checkpoints + external transparency log | audit | P0 |
| RF-09 | External benchmark adapters: AgentDojo + MCPTox | benchmarks | P2 |
| RF-10 | Declared task–tool contracts, minimal frontier | gating | slice 1 shipped (CAP-014) |
| RF-11 | Governed Programmatic Tool Calling | gating+composition | SCOPED |
| RF-12 | Database-enforced tenant isolation (RLS) | security | P2 |
| RF-13 | Runtime surface, authority paths and effect evidence | reference implementation | none |

§11 lists what was considered and excluded (TEE, zkML, blockchain anchoring,
fleet governance, fine-tuning defenses, SHADE-Arena as first-class benchmark
because it breaks the no-API-keys test contract). §12 is an unassessed intake
list (C-01..C-12) with no identifiers; nothing there may be cited.

## Provenance concepts, PROV (docs/assurance/provenance_concepts_v1.yaml)

PROV-01 DecisionEnvelope · 02 ToolSpec · 03 exact-call binding · 04 fresh
re-gate · 05 PolicyDecisionToken · 06 ExecutionLease · 07
GovernedToolDispatcher · 08 ToolSpec-changed refusal · 09 runtime capability
surface completeness · 10 non-transitivity of authority · 11 evidence
sufficiency tri-state · 12 authority/effect separation · 13 canonical
tool-call hash · 14 one-time lease nonce · 15 custody split as hard guard ·
16 task identity bound into the lease · 17 the authority-to-effect chain
taken together.

Each has a record `provenance/concepts/PROV-xx.yaml` (invariant,
first-recorded commit, spec/implementation/tests paths, related CAP/CLAIM,
`distinguishing_contribution`, `prior_art.reviewed`). All seventeen are
`classification: UNKNOWN`, `origin.status: claimed_original_contribution`.
`provenance/PRIOR_ART.yaml` lists sources PA-SRC-001..003 and `reviews: []`.
`provenance/EXTERNAL_ADOPTION.yaml` has EXT-0001..0005 (independent
reproduction of PROV-11, APS record for PROV-13, Probity pin for PROV-09,
own adapter, Federation discussion). The register records priority and
content, not novelty; the manifest gate refuses a record that upgrades its
own classification without a review.

## Claim register, CLAIM (docs/assurance/claim_register_v1.yaml)

Active: 001 (FAR=0% sim v2), 002 (AgentHarm, imported historical artifact,
cannot be regenerated here), 003 (historical regression), 005, 006 (AROMER
shadow-only), 009 (FA under neutral metadata, negative), 010 (blinded v3),
011 (anytime-valid bound), 012 (NEGATIVE: temperature failed SAP v3), 013,
014 (system demonstration), 017 (semantic binding gap finding), 019 (sealed
C-ext3, four of seven targets missed), 020 (ablation has no discriminating
power). Superseded: 004, 007, 008, 015, 016, 018. Quote the register row,
never the title alone.

## Negative results that constrain research choices (NEGATIVE_RESULTS.md)

Counts as of 2026-10-02 in the file header: 17 open, 27 accepted, 31
superseded. Newest: §74 Jev injection questions flag benign operator text
(open; V2.1 held-out, Norwegian flagged about twice English), §75 evidence
admission takes trust configuration and the clock on faith (open).

- §18 / CLAIM-012: consensus temperature failed fresh-data confirmation. Thermodynamic selection is closed; §38 withdrew the framing from the paper.
- §19: AgentHarm rescoring. FAR met, FBR=100% because the source is all-ESCALATE and protocols act on VERIFY. Blanket ESCALATE→VERIFY rewrite moved 19 harmful, 0 benign; locked by `tests/test_escalate_semantics_guard.py`. A dataset with per-case signals is required before resampling is wired.
- §20: more registry signatures changed no routing metric.
- §3: entropy backend is a token fingerprint, not Semantic Entropy (open, "solvable now", RF-06).
- §2/§8: contextual harm invisible in a single call; needs trajectory-level governance.
- §39: deterministic intent extractor caps read autonomy; semantic gates preempt argument routing (open, High).
- §42: a crosswalk reported four capabilities absent that were present. Audit findings are hypotheses until verified against code.
- §57: component ablation withdrawn; all six conditions FAR=0 including hard-blocks-removed.

## Code you will be pointed at

| Path | What it is | Runtime? |
|---|---|---|
| `remora/selective/risk_control.py` | `sgr_threshold`, `crc_threshold` (direct CRC criterion), Clopper-Pearson | library only |
| `remora/selective/crc.py` | weighted empirical selective router, explicitly not CRC | runtime selector (empirical) |
| `remora/selective/conformal.py` | split conformal, exchangeability assumed | runtime |
| `remora/selective/confidence_sequence.py` | anytime-valid bound | library |
| `remora/governance/control_protocols.py` | defer-to-trusted / trusted-edit / defer-to-resample, channel separation, suspicion-suppression guard | library, flag `REMORA_CONTROL_PROTOCOLS` |
| `remora/governance/procedure.py` | procedure obligations (RES-018) | runtime |
| `remora/semantic_entropy.py` | entropy backends; NLI backend unused by default | runtime (fingerprint) |
| `remora/toolcall/routing/sources/agentdojo.py` | AgentDojo adapter over pinned excerpt | offline |
| `remora/enforcement/lease.py`, `gate.py`, `resolved_effect.py`, `remora/execution/dispatch.py` | authority-to-effect chain | runtime |
| `remora/audit/hash_chain.py`, `merkle.py`, `anchor.py` | chain + Merkle primitives, external anchoring not wired | partial |
