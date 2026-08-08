# 13 — Research Frontier Roadmap (2026-07)

**Status: proposal, with one exception.** Every work package (WP) below is
unimplemented **except RF-10 slice 1**, which shipped on 2026-08-03 and is
recorded as CAP-014 in `docs/assurance/capability_register_v1.yaml`
(`IMPLEMENTED_LIBRARY`, discrimination unmeasured, so no accuracy number may be
quoted for it). Nothing else in this document is a claim. Every WP follows the
repo contract: a claim may only enter
`README.md` / `EVIDENCE_OF_CAPABILITY.md` after its artifact exists on disk, its
tests pass under `make test` (deterministic, no API keys), and `make audit`
verifies claim ↔ artifact consistency. Caveats travel with numbers.

**Method.** Gap analysis of the five load-bearing pillars — evidence, RAG,
tool-call gating, uncertainty routing, audit — against published work through
mid-2026, plus REMORA's own open findings (`NEGATIVE_RESULTS.md` §3
entropy-backend mismatch; the AgentHarm FBR=100% corner; the tamper-evident
limitation in the README Limitations section, registered as REM-025; the
REM-020/REM-021 deployment gates; the SAP v3 CWV result, validated but not
wired). RF-01…RF-09 were grounded against the working tree on 2026-07-30
(master @ `0646a87`); RF-10 was added on 2026-08-03 (master @ `f510cde`). The
"Already in the repo" subsections record what the draft's gap statements had to
be corrected against.

**Namespace note.** WP identifiers are RF-01…RF-10 (research frontier). The
`REM-` prefix is deliberately not used: it is the namespace of
`docs/assurance/remediation_register.yaml` (REM-001…REM-046, machine-consumed
by release-profile gating), and roadmap WPs are not remediation items. Where a
WP would close a registered remediation item (RF-08 ↔ REM-025), the WP says so
explicitly.

**Pick-list.** `docs/research/research_shelf_v1.yaml` is the machine-readable
companion to this document: one entry per candidate external component, each
carrying its source, whether that source was actually retrieved and when, what
REMORA already has, and the adoption decision. `scripts/check_research_shelf.py`
(run by `make audit`) refuses a shelf where an unretrieved source has been
adopted, where an ADOPTED entry names code or tests that do not exist on disk,
or where an author's reported numbers have been recorded in a way that could
read as REMORA's. Entries cross-reference work packages here by `roadmap_ref`,
and a test fails if that reference names no WP in this file. This document
holds the argument; the shelf holds the evidence that a pick is safe to make.

**Related documents.** `paper/future_state.md` (long-horizon research
directions; interface stubs only), `docs/11-benchmark-validation-plan.md`
(external-validation protocol this roadmap's benchmark WPs extend),
`docs/methods/theoretical_foundations_proposals_v1.md` (registered proposals
that RF-05 partially restates — cross-referenced there).

## 0. Coverage assessment

| Pillar | REMORA today | Frontier state (mid-2026) | Gap |
|--------|--------------|---------------------------|-----|
| Tool-call gating | Static hard-block invariants (Stage 1) drive the v2 safety floor; tainted-argument floor since engine v4 (2026-07-30): tainted+critical → ESCALATE, otherwise VERIFY floor, with OPA/Rego parity; session-level cumulative-risk guards | Declarative policy DSLs with formal semantics (AgentSpec, ICSE'26); context-derived least-privilege (Progent 2025); capability/IFC provenance on arguments (CaMeL 2025); tool-registry integrity vs. poisoning (MCPTox 2025; OWASP Agentic Top 10 2026 ASI04) | **High** — taint is one caller-asserted bit (no per-value labels, no propagation, no flow policy); tool metadata is never ingested or verified |
| Uncertainty routing | Split-conformal calibration (`remora/selective/conformal.py`, exchangeability assumption); weighted empirical selective router (`crc.py`, distribution-free bound explicitly disclaimed post-R3-01); anytime-valid FAR confidence sequence shipped for REM-020; TokenFingerprint entropy (NLI backend unused); SAP v3 CWV validated but not wired | Drift-aware/online conformal (ACI, conformal PID, PromptShift-CRC 2026); selective CRC; conformal decision/action risk control for agents (CORA 2026); anytime-valid e-process monitoring; multi-signal selective prediction ("entropy alone is insufficient", 2026) | **High** — but see RF-05: the selector the draft wanted to drift-harden was falsified by SAP v3; recalibration needs a validated signal first |
| Evidence / RAG | Evidence-verification oracles; `EvidenceLabel.INSUFFICIENT` + citation-coverage escalation in the evidence router; zero-signal on empty retrieval | Retrieval sufficiency classification routed to abstention (ICLR'25); adversarial corpus robustness (PoisonedRAG, USENIX Sec'25; AgentPoison, NeurIPS'24); citation-level attribution eval (ALCE) | **Medium** — no distinct insufficient-context judge outcome, no poisoned-corpus benchmark |
| Escalate / VERIFY resolution | VERIFY = "seek more evidence"; on AgentHarm every benign variant routes to ESCALATE (human review) — FBR=100%, FAR=0.0% | AI-control protocols: defer-to-trusted, trusted editing, defer-to-resample, resample-for-incrimination (Greenblatt et al. 2024 → SHADE-Arena line, 2025–26); adaptive-attack results warn against leaking monitor rationale | **High** — this literature is the direct fix for the FBR problem |
| Audit | DecisionEnvelope + SHA-256 hash chains (tenant + shadow/replay); Merkle checkpoint primitives implemented and tested (`remora/audit/merkle.py`, `anchor.py`) but unwired to the live chains; no external anchoring (REM-025, NOT_STARTED); tamper-evident, not tamper-proof | External transparency logs (RFC 6962, Sigstore Rekor); in-toto/SLSA-style attestation; proof-carrying agent actions (2026); EU AI Act Art. 12 record-keeping binding for high-risk systems from Aug 2026 | **Medium** — wiring + external publishing, closes a stated limitation; regulatory deadline makes it timely |
| Benchmarks | In-house simulators (toolcall v1/v2/blind v3) + one externally authored dataset already adapted and scored: AgentHarm (CLAIM-002) | Externally authored agent-security benchmarks: AgentDojo (NeurIPS'24), MCPTox (2025) | **Medium** — widens dataset independence; does NOT close the external-replication limitation (run independence is a different evidence level) |

**Priority order after grounding** (rationale in §10):
P0 RF-04, RF-06, RF-08 · P1 RF-01, RF-02 (slice 1) · P2 RF-07, RF-09 ·
P3 RF-03, RF-05.
(The pre-grounding draft had RF-01 and RF-05 higher; §10 records why they
moved.)

---

## RF-01 — Tool-registry integrity (tool-poisoning defense) `[gating]` `[P1, effort S]`

**Gap (grounded).** Stage 1 gates actions from `PolicyObservation` fields; tool
descriptions and schemas are never ingested or verified at any point —
`GovernedToolDispatcher.register()` (`remora/enforcement/lease.py`) binds
name → callable only, and no artifact pins tool-metadata content.
(`docs/assurance/capability_register_v1.yaml` is a maturity register for
REMORA's own mechanisms, not a tool registry.) In the shipped research profile
the registry is app-side code (`servers/tool_registry_research.py`), so
metadata drift requires a git commit; the unchecked-description exposure
becomes live once MCP/external tool sources are fronted (the REM-024/REM-030
residual). Tool descriptions are an indirect-prompt-injection channel (OWASP:
"trust gap between connect time and runtime"), and MCPTox reports that current
agents rarely refuse poisoned tool metadata.

**Already in the repo.** `docs/assurance/red_team_plan_v1.md` AT-04
("Misleading tool descriptions") is marked Covered via the per-call
critical-alternative gate (`tests/test_red_team_v1.py::test_rt_04_*`) — a
behavioral defense against mislabeled `action_type`. RF-01 adds the
complementary registry-side defense: content-hash pinning of the metadata
itself. `docs/security/owasp_genai_mapping.md` already claims "tool schema
validation, allowlist, dry-run" for tool calls; RF-01 is scoped to the
registry/content-pinning residual so it does not contradict that row.
Canonical-hashing infrastructure to reuse: `canonical_tool_call_hash`
(`remora/policy/observation.py`).

**Literature.**

- Beurer-Kellner & Fischer (Invariant Labs, 2025). *Tool Poisoning Attacks*
  (first naming of TPA).
- Wang et al. (2025). *MCPTox: A Benchmark for Tool Poisoning Attack on
  Real-World MCP Servers.* arXiv:2508.14925.
- OWASP (Dec 2025). *Top 10 for Agentic Applications 2026* — ASI02 tool misuse,
  ASI04 agentic supply chain, ASI06 memory/context poisoning.
- OWASP Community. *MCP Tool Poisoning* attack entry (connect-time vs. runtime
  trust gap).
- Debenedetti et al. (2024). *AgentDojo.* NeurIPS D&B. arXiv:2406.13352
  (indirect-injection evaluation substrate).

**Artifact.**

- `schemas/tool_pin_register_schema.yaml` — pin register schema:
  `schema_sha256`, `description_sha256`, `pinned_at`, `tofu` per tool. (Not
  named "capability_register_v2": that name is reserved for a future revision
  of the assurance maturity register, which is a different document.)
- `artifacts/tool_integrity/tool_drift_report.json` — machine-readable diff on
  every detected change (old hash, new hash, unified diff of description).
  (Not named `drift_report`/`DriftReport` — that vocabulary is taken by
  alignment drift in `remora/governance/continual_realigner.py`.)
- `docs/research/tool_integrity.md` — threat model: poisoned description,
  rug-pull update, line-jumping at discovery; cross-references AT-04.
- `tests/test_tool_integrity.py`

**Test.**

- pinned schema+description → PASS; any byte drift → gate outcome ESCALATE
  (not silent re-pin).
- unpinned tool under `strict` mode → ESCALATE; under `tofu` mode → pin-and-log,
  envelope records first-seen hash.
- description containing imperative-instruction patterns → flagged in drift
  report (heuristic lint, non-blocking; blocking is hash-based only, so the
  deterministic guarantee never depends on the lint).
- fixture corpus of 20 poisoned descriptions (committed, offline) → 0 reach the
  planner unflagged.

**Code.** `remora/enforcement/tool_integrity.py` — beside `lease.py`/`gate.py`/
`token.py`, which it integrates with (there is no `remora/gate/` package; the
WP also introduces the tool-metadata carrier itself, since no `ToolDefinition`
type exists in the repo). Reference implementation, stdlib-only, deterministic:

```python
# remora/enforcement/tool_integrity.py
"""Hash-pinned tool metadata verification (RF-01).

Stage 1 invariant: a tool whose schema or description does not match its
pinned SHA-256 MUST NOT be exposed to the planner. Drift => ESCALATE.
Deterministic, offline, stdlib-only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PinMode(str, Enum):
    STRICT = "strict"   # unpinned tool => ESCALATE
    TOFU = "tofu"       # unpinned tool => pin on first use, log first-seen


class IntegrityOutcome(str, Enum):
    OK = "ok"
    PINNED_FIRST_USE = "pinned_first_use"
    DRIFT = "drift"          # => ESCALATE upstream
    UNPINNED = "unpinned"    # strict mode => ESCALATE upstream


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def schema_digest(schema: dict) -> str:
    return hashlib.sha256(_canonical(schema)).hexdigest()


def description_digest(description: str) -> str:
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ToolPin:
    tool_name: str
    schema_sha256: str
    description_sha256: str


@dataclass
class IntegrityReport:
    tool_name: str
    outcome: IntegrityOutcome
    expected: ToolPin | None
    observed: ToolPin
    detail: str = ""

    def to_envelope_block(self) -> dict:
        """Serializable block for the DecisionEnvelope audit chain."""
        return {
            "check": "tool_integrity_v1",
            "tool": self.tool_name,
            "outcome": self.outcome.value,
            "expected_schema_sha256": self.expected.schema_sha256 if self.expected else None,
            "observed_schema_sha256": self.observed.schema_sha256,
            "expected_description_sha256": self.expected.description_sha256 if self.expected else None,
            "observed_description_sha256": self.observed.description_sha256,
            "detail": self.detail,
        }


@dataclass
class ToolIntegrityGate:
    mode: PinMode = PinMode.STRICT
    pins: dict[str, ToolPin] = field(default_factory=dict)

    @classmethod
    def from_register(cls, register: dict, mode: PinMode = PinMode.STRICT) -> "ToolIntegrityGate":
        pins: dict[str, ToolPin] = {}
        for cap in register.get("tools", []):
            if "schema_sha256" in cap and "description_sha256" in cap:
                pins[cap["name"]] = ToolPin(
                    tool_name=cap["name"],
                    schema_sha256=cap["schema_sha256"],
                    description_sha256=cap["description_sha256"],
                )
        return cls(mode=mode, pins=pins)

    def verify(self, tool_name: str, schema: dict, description: str) -> IntegrityReport:
        observed = ToolPin(tool_name, schema_digest(schema), description_digest(description))
        pin = self.pins.get(tool_name)
        if pin is None:
            if self.mode is PinMode.TOFU:
                self.pins[tool_name] = observed
                return IntegrityReport(tool_name, IntegrityOutcome.PINNED_FIRST_USE,
                                       None, observed, "trust-on-first-use pin")
            return IntegrityReport(tool_name, IntegrityOutcome.UNPINNED,
                                   None, observed, "no pin in register (strict mode)")
        if pin == observed:
            return IntegrityReport(tool_name, IntegrityOutcome.OK, pin, observed)
        drift_of = []
        if pin.schema_sha256 != observed.schema_sha256:
            drift_of.append("schema")
        if pin.description_sha256 != observed.description_sha256:
            drift_of.append("description")
        return IntegrityReport(tool_name, IntegrityOutcome.DRIFT, pin, observed,
                               f"drift in: {','.join(drift_of)}")
```

**Wiring:** `IntegrityOutcome.DRIFT` and `.UNPINNED` (strict) map to the
existing ESCALATE path in repo decision vocabulary (`DecisionAction.ESCALATE` /
lease-refusal reason), mirroring the existing `tool_args_hash_mismatch`
fail-closed refusal at dispatch; metadata attaches as an optional argument to
`GovernedToolDispatcher.register()`. The report block is appended to the
DecisionEnvelope. Rug-pull coverage falls out for free: re-verification runs on
every gate pass, not once at connect.

**Acceptance.** All committed poisoned-fixture tasks blocked or escalated; zero
silent re-pins; `make audit` maps the claim "tool metadata is hash-verified on
every gated call" to `artifacts/tool_integrity/`.

**Verdict after grounding: soon (P1, schedule with MCP/external tool
fronting).** The direction is genuine and effort S is realistic, but it closes
no open published finding: AT-04 is published as Covered, and the research
profile's app-side registry means metadata cannot drift at runtime today. Land
it as the prerequisite hardening immediately before or alongside external tool
fronting (REM-024/REM-030 residual), after the Assurance Kernel Freeze
(#35/#37/#38/#39 — open issue #37 touches the same execution path). First
slice: the module + pin the two research-profile tools + tests; doc and drift
report artifact second.

---

## RF-02 — Argument provenance / capability labels (CaMeL-class IFC) `[gating+evidence]` `[P1 slice 1, P2 full, effort L]`

**Gap (grounded).** Since 2026-07-30 (RemoraDecisionEngine-v4, issue #40,
PR #94) Stage 1 enforces a tainted-argument floor: untrusted-derived arguments
can never auto-accept (`TAINTED_ARGUMENT_VERIFY`), and at CRITICAL risk they
escalate outright (`TAINTED_ARGUMENT_ESCALATE`), with Rego parity
(`remora_action_gate.rego`) and conformance golden cases
(`scripts/opa_conformance.py`). What REMORA still lacks is a CaMeL-class
provenance model *above* that boolean: per-value labels with source/capability
sets, taint derivation and propagation across tool outputs into later
arguments, flow policies (`flow_allowed(value_label, sink_field)`), and a
sanitize-and-revalidate declassification path (issue #40 option b, explicitly
deferred in `decision_engine.py`). Today taint is a single caller-asserted bit
per call — an integration that never computes it gets no protection, and
`PolicyObservation.from_record` does not map `argument_tainted`, so
record-driven replay/shadow ingestion silently drops the signal.

**Already in the repo.** The v4 taint floor
(`remora/policy/decision_engine.py`, reason codes in `remora/policy/report.py`)
is locked by `NEGATIVE_RESULTS.md` §2 (structural gates) and
`tests/test_balanced_validation.py::TestStructuralDefenseIsPrincipled`; the
benchmark ground-truth field `argument_tainted` lives in
`remora/toolcall/schema_v3.py`. The published finding this WP is the vehicle
for: `docs/assurance/best_practice_gap_audit_v1.md` gap #1 (High,
"capability confinement (CaMeL)") — whose taint half is itself now partially
stale. **Disambiguation:** argument provenance (this WP) is distinct from
*result provenance* (`result_provenance_v1/v3`, PR #101, issues #32/#88),
which attests result artifacts and worktree state — use "argument provenance"
or "value labels", never bare "provenance".

**Literature.**

- Debenedetti et al. (2025). *Defeating Prompt Injections by Design* (CaMeL).
  arXiv:2503.18813 — control/data-flow separation + capability policies; solves
  the AgentDojo security suite with provable security at modest utility cost.
- Denning & Denning (1977). *Certification of programs for secure information
  flow.* CACM (the IFC root).
- Debenedetti et al. (2024). *AgentDojo.* arXiv:2406.13352 (evaluation
  substrate).
- Willison (2025). *CaMeL offers a promising new direction* — honest account of
  the policy-authoring and user-fatigue costs; quote these limits alongside any
  adoption claim.

**Artifact.**

- `docs/research/argument_provenance.md` — label lattice:
  `{origin: user|system|tool:<name>|corpus:<doc_sha>, readers: set}`;
  propagation rules through envelope stages; declassification requires
  ESCALATE; explicit "not result provenance" note.
- `schemas/value_label_schema.yaml` (schemas/ convention is snake_case YAML).
- `tests/test_argument_provenance.py` (`tests/test_provenance_dag.py` and
  `tests/test_result_provenance_writer.py` already exist).

**Test.**

- argument derived from untrusted tool output → egress-class tool ⇒ blocked,
  deterministic.
- same argument after explicit human ESCALATE-approval ⇒ allowed, approval
  recorded in envelope.
- label propagation is monotone (no label laundering through string ops in the
  simulator).
- record-ingestion parity: `from_record` carries `argument_tainted` (closes the
  silent-default-False hole).

**Code.** `remora/policy/argument_provenance.py` — `propagate()`, `Label`,
`LabeledValue`, Stage 1 predicate `flow_allowed(action, labeled_args, policy)`
(beside `decision_engine.py`/`observation.py`; `remora/provenance.py` is taken
by result provenance). Label-aware flooring is an engine-behavior change: ship
it as a RemoraDecisionEngine-v5 version bump with new conformance golden cases
and Rego parity, per the v4 precedent (`remora/policy/versioning.py`).

Simulator-first: implement in the deterministic benchmark environment before
any live adapter, mirroring how the toolcall benchmarks were built.

**Acceptance.** A committed exfiltration suite (recipient-swap, filename
smuggling, parameter smuggling per the 2026 CSA agentic-MCP pattern) shows 0
unauthorized flows at a measured utility cost, reported with CI, cluster-level
N, in the v3-blind style.

**Verdict after grounding: slice 1 soon, full WP P2.** The draft's acute
scenario (poisoned recipient passes Stage 1) is already blocked by the merged
v4 floor when `argument_tainted` is set — but the `from_record` hole is a live
integration defect in the shipped gate, and slice 1 (map `argument_tainted`
through `from_record` + the envelope, plus `value_label_schema.yaml` degrading
to the existing boolean; no behavior change, golden cases stay green) is
small and worth doing near-term. The full lattice/flow-predicate work stays P2,
sequenced after the interception probe (flow labels are only meaningful once
tool-call interception is proven; see `experiments/agentharm/INTERCEPTION_NOTES.md`).

---

## RF-03 — Policy DSL with formal semantics + trajectory invariants `[gating]` `[P3, effort M]`

**Gap (grounded).** Per-call policy is already expressible declaratively via
the OPA/Rego adapter (`remora/policy/opa_adapter.py`), with structural parity
and a monotone hard-guard floor enforced in CI (`tests/test_opa_parity.py`,
`scripts/opa_conformance.py` — a mandatory job with pinned OPA). But the Python
engine remains authoritative: the shipped Rego is an illustrative example that
passes safety parity, not strict identity, and neither Rego nor the typed
invariants in `remora/policy/invariants.py` carry formal semantics of the
AgentSpec kind. On the trajectory side, signals exist — session aggregates gate
decisions (`session_cumulative_risk`/`session_action_count` hard guards in
`decision_engine.py`) and the agent hook runs a cross-call Lyapunov tracker
with `abort_window` and autonomy degradation (`remora/agent_hook/lyapunov_tracker.py`,
`remora/lyapunov.py`, PR #102) — but there is no declarative way to express
multi-step *patterns* ("read secret THEN network send"); those remain implicit
in scalar aggregates and stability heuristics. Connects to the pre-registered
Trust Stability Forecasting harness (`experiments/tsf/PREREGISTERED.md` —
synthetic harness only, no real-system evidence).

**Literature.**

- Wang, Poskitt & Sun (2026). *AgentSpec: Customizable Runtime Enforcement for
  Safe and Reliable LLM Agents.* ICSE 2026 — rule r = (trigger η, predicates P,
  enforcement E), formal semantics.
- Xiang et al. (2024). *GuardAgent.* arXiv:2406.09187 (guardrails via a guard
  agent; per-instance authoring cost is the caveat).
- Leucker & Schallhart (2009). *A brief account of runtime verification.*
  J. Log. Algebr. Program. (LTL/monitor background).
- Bhardwaj (2026). *Agent Behavioral Contracts* — probabilistic compliance
  guarantees, drift bounds (per-agent formal layer above per-call rules).

**Artifact.**

- `docs/research/policy_dsl.md` (grammar + small-step semantics);
- `policies/*.remora.yaml` — the current invariants re-expressed and proven
  equivalent by test. The DSL files must (a) state their compilation target
  (Rego and/or `PolicyInvariant` objects), (b) subsume the existing
  `rego_examples/` layout, and (c) enter `compute_policy_bundle_hash`
  (`remora/policy/versioning.py`) so `AuditBlock.policy_bundle_hash` reflects
  DSL changes.

**Test.** `tests/test_policy_dsl.py` — golden evaluation table (every rule ×
crafted state → expected outcome); equivalence suite: DSL-compiled gate
reproduces byte-identical decisions vs. the legacy Python invariants on the
full v2 benchmark, with `scripts/opa_conformance.py --strict` as the target
gate; sequence tests for two- and three-step forbidden patterns.

**Code.** `remora/policy/dsl.py` (parser + evaluator, no eval/exec);
`remora/policy/trajectory_monitor.py` — explicit finite-state machines over
envelope history, consuming/extending the existing LyapunovTracker session
state (`.remora_session`) rather than a second session store, with verdicts
flowing into `PolicyObservation` session fields so the decision-path guards
and OPA export see them without a new parity exclusion.

**Acceptance.** Byte-identical v2 benchmark decisions after migration; at least
three trajectory rules impossible to express per-call, each with a committed
failing-then-passing episode.

**Verdict after grounding: defer.** Roughly half the drafted gap is already
closed (declarative per-call policy with a CI-enforced safety-parity
relationship exists). The residual — formal semantics + FSM pattern monitors —
closes no published finding, and the Lyapunov `abort_window` semantics just
landed and should stabilize first. If promoted later, the smallest first slice
is a trajectory FSM that re-expresses the existing session guards and
`abort_window` declaratively and proves equivalence.

---

## RF-04 — VERIFY resolution via AI-control protocols (the FBR fix) `[routing/escalate]` `[P0, effort M]`

**Gap (grounded).** AgentHarm external validation (CLAIM-002,
`results/external_benchmark_agentharm_v1.json`): FAR 0.0% (Wilson 95% CI
[0.00%, 1.81%]) on 208 harmful scenarios, FBR 100.0% on the 208 benign
variants — all 416 scenarios resolve to ESCALATE. Two caveats the draft
conflated, kept separate here: (a) *benchmark scope* is intent-gating, not
tool-call interception (`experiments/agentharm/INTERCEPTION_NOTES.md`);
(b) the *FBR mechanism* is that benign variants share `harm_category` with
their harmful counterparts, so the category→risk-tier mapping triggers the
VERIFY floor and every benign variant lands on the ESCALATE/human-review path
(not a terminal DENY) — while FAR=0.0% is separately carried by Stage-1
hard-block invariants. That routing is exactly what the AI-control literature
resolves: instead of terminal review, suspicious actions get interventions —
defer-to-trusted, trusted editing, defer-to-resample,
resample-for-incrimination — buying back benign utility without giving up the
safety floor.

**Already in the repo.** The only existing VERIFY/ESCALATE resolution
machinery is `remora/governance/review_queue.py` (REM-032/REM-033: only VERIFY
and ESCALATE enqueue; TTL expiry → ABSTAIN, "never auto-accept, never
indefinite silent pending") — a control protocol extends these semantics.
VERIFY floors live in `remora/policy/decision_engine.py`; the cascade already
has a budget concept (budget-capped VERIFY in `remora/cascade/engine.py`);
`remora/verifier/llm_judge.py` is an existing trusted-monitor building block.
The paper already positions REMORA in the Greenblatt et al. control taxonomy
and names the FBR=100% corner "an explicit target for REMORA's calibration
roadmap" (`paper/remora_paper.md` §2.11); `docs/assurance/best_practice_gap_audit_v1.md`
grades the AI-control protocol row yellow ("no formal control-protocol
red-team evaluation"). The Neyman-Pearson framing of the FAR/FBR corner is
already written in `docs/methods/theoretical_foundations_proposals_v1.md`
item 5 — cite it, don't restate it.

**Re-run protocol constraint.** CLAIM-002 is an imported historical result
(produced in the main implementation repo via the AROMER `/decide` worker
path; not regenerable here — `docs/assurance/rebenchmark_protocol_v1.md`). A
control-protocol evaluation therefore produces a **new** pre-registered
protocol, artifact, and claim ID — e.g. a deterministic offline re-scoring of
the 416 frozen scenario instructions already embedded in the artifact through
the local decision path — and cannot "update" CLAIM-002's number.

**Literature.**

- Greenblatt et al. (2024). *AI Control: Improving Safety Despite Intentional
  Subversion.* arXiv:2312.06942 — trusted monitoring, defer-to-trusted, trusted
  editing.
- Bhatt et al. (2025). *Ctrl-Z: Controlling AI Agents via Resampling.*
  arXiv:2504.10374 — resample protocols, safety/usefulness Pareto.
- Kutasov et al. (2025). *SHADE-Arena* — control evaluation in diverse agentic
  environments.
- Anonymous (2025). *Evaluating Control Protocols for Untrusted AI Agents.*
  arXiv:2511.02997 — resampling-for-incrimination + defer-on-critical raised
  safety 50%→96% in SHADE-Arena; red-team iteration included.
- (2025). *Adaptive Attacks on Trusted Monitors Subvert AI Control Protocols.*
  arXiv:2510.09462 — defer-to-resample can backfire under adaptive attack;
  design against this.
- (2026). *Retrying vs Resampling in AI Control.* arXiv:2605.26047 —
  monitor-rationale feedback to the gated agent helps adversaries iterate
  stealthier attacks. Direct design rule: the gate must not return its
  rationale on the agent channel.
- (2026). *SLEIGHT-Bench.* arXiv:2605.16626 — evasion attacks against monitors;
  use as adversarial test inspiration.

**Artifact.**

- `docs/research/verify_control_protocols.md` — VERIFY strategy set
  {seek-evidence (status quo), defer-to-trusted, trusted-edit,
  defer-to-resample(k)}, selection policy, and the rationale-channel rule.
- `artifacts/verify_protocols/agentharm_rescore_v1.json` — new pre-registered
  protocol (frozen decision rule committed before results, PREREGISTERED.md
  precedent): FAR/FBR per strategy, per-split N, Wilson CI.
- `tests/test_verify_protocols.py`

**Test.**

- deterministic replay-arena episodes where benign-but-flagged tasks complete
  under defer-to-resample while every harmful sibling stays blocked (paired
  fixtures).
- rationale-leak test: agent-visible channel after a block contains no monitor
  scores, no rule identifiers, no diff of what would have passed.
- adaptive-attack regression: the arXiv:2510.09462 failure pattern
  (suspiciousness suppression across resamples) encoded as a fixture; protocol
  must escalate on minimum-suspiciousness manipulation.
- safety invariants: the protocol acts only above Stage-1 hard blocks
  (FAR floor untouched); `review_queue`'s never-auto-accept invariant is
  preserved or formally amended in the same WP;
  `tests/policy/test_governance_intelligence_never_weakens_policy.py` stays
  green.

**Code.** `remora/governance/control_protocols.py` — beside `review_queue.py`,
today's sole VERIFY/ESCALATE consumer (there is no `remora/routing/` package):
`VerifyStrategy` enum, `resolve_verify(envelope, k, trusted_oracle)`; trusted
oracle = existing deterministic policy gate acting as editor (no new model
dependency; the "trusted model" role is played by the deterministic layer in
the simulator, a documented substitution). Cascade-side hooks extend the
existing budget-VERIFY in `remora/cascade/engine.py`.

**Acceptance.** Pre-registered target on the new protocol: FAR unchanged at
0.0% (Wilson-bounded), FBR reduced from 100% to a pre-committed threshold
(propose ≤40% for the first round — write the number down before the run, in
SAP-v3 style). If the target is missed, the result ships in
`NEGATIVE_RESULTS.md`, not the README.

**Verdict after grounding: start now.** Closes findings the repo has already
published against itself (paper §2.11 target; gap-audit yellow row); every
in-repo dependency exists; the only blocked piece — the CLAIM-002 headline —
is handled by the new-protocol scoping above. First slice: flag-gated
`control_protocols.py` + invariant tests + the design doc with the frozen
decision rule for the offline re-scoring.

---

## RF-05 — Drift-aware conformal + anytime-valid deployment monitoring `[routing]` `[P3, effort M]`

**Gap (grounded — the draft's premise did not survive).** The draft wanted to
drift-harden "τ*=0.2032 locked on a training split". Grounding: (a) the
on-disk artifact was regenerated in the SAP v2 live round and now carries
τ*=0.4991; 0.2032 survives only in the frozen AgentHarm config
(`experiments/agentharm/tau_config.yaml`, C7 protocol) and stale doc text.
(b) More fundamentally, the pre-registered SAP v3 round (CLAIM-012, N=1231
fresh items) falsified temperature as a selective signal — it ranks *worse*
than a calibrated confidence baseline, and SGR certifies no coverage. There is
currently no validated selector whose calibration needs drift-awareness;
drift-hardening a falsified selector produces nothing citable. (c) The
anytime-valid half is substantially shipped for the gate that needed it:
`remora/selective/confidence_sequence.py` (time-uniform Beta-mixture
supermartingale — an e-process) with `results/far_confidence_sequence_v1.json`
already supplements REM-020's longitudinal FAR gate, replacing the fixed-N
peeking problem. (d) Runtime shift *detection* with conservative fallback
exists (`remora/selective/drift_detector.py` → VERIFY on
`distribution_shift_detected`); adaptive *recalibration* does not. (e) CRC/SGR
/LTT machinery exists as library code (`remora/selective/risk_control.py`),
explicitly unwired pending a fresh-data effect. What genuinely remains: online
conformal (ACI/PID) for whichever selector survives the pending rebenchmark
protocol, and extending the e-process from a one-shot script to continuous
shadow-stream monitoring.

**Already in the repo.** `remora/selective/conformal.py` (split-conformal —
the component that actually assumes exchangeability); `crc.py` — note that
per external review R3-01 `CovariateShiftCRC` is an alias of
`WeightedEmpiricalSelectiveRouter` and *explicitly disclaims* the
E[L(λ̂)] ≤ α + 1/(n+1) bound (do not describe it as CRC-with-guarantee);
`confidence_sequence.py` + `tests/test_confidence_sequence.py`;
`drift_detector.py`; `risk_control.py`. ACI is already a registered proposal:
`docs/methods/theoretical_foundations_proposals_v1.md` §8 prescribes
`remora/selective/adaptive_conformal.py`, places the ACI update loop in the
caller/AROMER layer (the engine is stateless), and flags online threshold
adaptation as a new attack surface (adversarial stream manipulation drags the
threshold) that must be covered before shipping. Deployment-gate reality: the
SHADOW_PILOT→CONTROLLED_PILOT gate set is REM-020+021+022+023
(`docs/assurance/release_profiles_v1.yaml`); progression is blocked on REM-021
(independent human review, NOT_STARTED), not on statistics.

**Literature.**

- Gibbs & Candès (2021). *Adaptive Conformal Inference Under Distribution
  Shift.* NeurIPS. arXiv:2106.00170.
- Angelopoulos, Candès & Tibshirani (2023). *Conformal PID Control for Time
  Series Prediction.* NeurIPS. arXiv:2307.16895.
- Barber, Candès, Ramdas & Tibshirani (2023). *Conformal Prediction Beyond
  Exchangeability.* Ann. Statist. arXiv:2202.13415.
- Angelopoulos, Bates, Fisch, Lei & Schuster (2024). *Conformal Risk Control.*
  ICLR. arXiv:2208.02814 (cited for the loss-general form).
- (2026). *PromptShift-CRC: Drift-Aware Conformal Risk Control for Foundation
  Models Under Prompt and Domain Shift.* arXiv:2606.15964.
- Xu, Guo & Wei (2025). *Selective Conformal Risk Control.* arXiv:2512.12844.
- (2026). *CORA: Conformal Risk-Controlled Agents.* arXiv:2604.09155 — controls
  the harmful-action rate of executed actions under an autonomy budget; closest
  published framing to REMORA's Stage 4 objective.
- (2026). *When Can Conformal Risk Control Certify LLM Outputs? Bounds,
  Impossibility, and Adaptation.* arXiv:2606.29054 — know the impossibility
  results before claiming certification.
- Ramdas, Grünwald, Vovk & Shafer (2023). *Game-Theoretic Statistics and Safe
  Anytime-Valid Inference.* Statist. Sci. arXiv:2210.01948 — e-processes for
  continuous monitoring.

**Artifact.**

- `docs/research/adaptive_conformal.md` — when recalibration is allowed, what
  invalidates the guarantee, and the exact statement of what is still
  guaranteed under shift (per 2606.29054, some certifications are impossible;
  say so); threat-model section for adversarial threshold-dragging per
  proposals §8.
- `artifacts/adaptive_conformal/drift_streams/` — committed synthetic drift
  streams (seeded); coverage-trace results go to `results/`.
- `docs/assurance/eprocess_monitoring_spec_v1.md` — e-process definition for
  the unsafe-rate bound that gates SHADOW→CONTROLLED transitions (spec docs
  follow the `docs/assurance/*_spec_v1.md` convention).

**Test.**

- `tests/test_adaptive_conformal.py` — under committed covariate-shift streams:
  ACI/PID variants maintain target coverage within tolerance; a static
  threshold demonstrably loses coverage on the same streams (the negative
  control is part of the test).
- `tests/test_eprocess.py` — e-process never exceeds the α-budget under the
  null across 10⁴ seeded simulated deployment runs; stopping rule is
  anytime-valid (asserted by construction + simulation).

**Code.** `remora/selective/adaptive_conformal.py` (the path proposals §8
already prescribes; ACI + PID threshold controllers behind a flag; default
remains the locked calibration until the artifact exists); e-process extension
inside `remora/selective/confidence_sequence.py` (or
`remora/selective/eprocess.py`) — continuous monitoring over the shadow
decision stream, beyond the current one-shot script; operational glue in the
existing `remora/observability/` package (there is no `remora/monitoring/`).

**Acceptance.** Deployment-monitoring criteria re-expressed as e-process
thresholds where a fixed-N interval is currently used (REM-020's gate already
has a supplementary anytime-valid bound; extend, don't duplicate).

**Verdict after grounding: defer (was P1 in the draft).** (1) The calibration
target no longer exists — the rebenchmark protocol must first yield a selector
that survives fresh-data validation. (2) The anytime-valid half is largely
shipped for the only gate that needed it. (3) Deployment progression is
blocked on REM-021 human review, not statistics — this WP closes no gate on
the critical path. Revisit as "soon" once the rebenchmark round validates a
selector; the first slice then is `adaptive_conformal.py` implementing the
Gibbs–Candès recursion with a shadow-replay coverage-under-induced-shift
artifact, per the acceptance spec already written in proposals §8.

---

## RF-06 — Semantic-entropy backend parity + CWV integration `[uncertainty]` `[P0, effort M–L]`

**Gap (grounded).** Two of REMORA's own findings, not external ones. (1)
`NEGATIVE_RESULTS.md` §3 (Active): every reported benchmark used
`TokenFingerprintBackend`; the NLI Semantic Entropy backend described in the
paper was never used for a reported result. The backend itself is already
first-class and tested (`NLISemanticBackend` and `make_backend(prefer_nli=True)`
in `remora/semantic_entropy.py`; fallback path covered in
`tests/test_semantic_entropy.py`) — the gap is *execution and a reported parity
artifact*, not code promotion. Local execution is blocked by a Windows
application-control policy on `torch/lib/shm.dll` (WinError 4551, documented in
§3), but all CI runners are ubuntu-latest and `requirements-lock.txt` already
pins `torch` and `sentence-transformers` — the CI-Linux route is fully
available (add an `nli` extra to `pyproject.toml`; none exists). (2) SAP v3:
calibrated confidence-weighted voting (CWV) survived pre-registration — 87.8%
vs 85.1% majority accuracy on the untouched N=368 test split of the 1231-item
fresh corpus, paired exact McNemar 11–1 discordants, p=0.0064 (CLAIM-013) —
but vs the dev-selected best single model (85.6%) the improvement is
directional only (p=0.077), and under family-wise Bonferroni-3 no arm
certifies at all. CWV is not integrated, and as of 2026-08-08 the README no
longer lists it among measured capabilities — it is recorded there as measured
but not adopted. Both are close-the-loop items the frontier
literature sharpens: entropy alone is a demonstrably insufficient
selective-prediction signal.

**Governance constraint.** SAP v3 deviation D-3
(`docs/assurance/statistical_analysis_plan_v3.md`) authorized *no engine
wiring* from that round, and CLAIM-013's caveat requires a separate frozen
confirmation round for promotion. CWV therefore ships flag-gated,
default-off, shadow-mode only; default-on needs its own pre-registered round —
this WP cannot claim to deliver that.

**Effort correction.** Backend parity against the *reported* results requires
new oracle inference: neither the SAP v3 collection nor the selective N302/N500
results store raw response texts (`NEGATIVE_RESULTS.md` §3 replication notes),
and re-collection must follow the post-2026-07-28 fingerprint semantics.
Budget the parity half M–L with live-oracle cost; the CWV port and the
CI NLI-execution slice are S.

**Literature.**

- Farquhar, Kossen, Kuhn & Gal (2024). *Detecting hallucinations in large
  language models using semantic entropy.* Nature 630:625–630.
- Kuhn, Gal & Farquhar (2023). *Semantic Uncertainty.* ICLR. arXiv:2302.09664.
- Kossen et al. (2024). *Semantic Entropy Probes.* arXiv:2406.15927 — cheap
  approximation if NLI cost is the blocker.
- (2026). *Entropy Alone is Insufficient for Safe Selective Prediction in
  LLMs.* arXiv:2603.21172 — motivates multi-signal (CWV) routing.
- Abbasi-Yadkori et al. (2024). *Mitigating LLM Hallucinations via Conformal
  Abstention.* arXiv:2405.01563 — the abstention-side pairing.

**Artifact.**

- `results/se_backend_parity_smoke.json` (slice 1) — NLI vs TokenFingerprint
  clustering compared on a fixed committed paraphrase corpus, produced by a
  CI-Linux job actually executing `NLISemanticBackend`.
- `artifacts/entropy_backend_parity/report.json` (full) — re-scored comparisons
  per operating point against the canonical baselines
  (`results/selective_trust_curve_results.json`, N=302, and
  `results/selective_n500_holdout_results.json`); requires new inference runs.
  Either the paper's backend claim is repaired or the paper text changes — one
  of the two; claim hygiene forbids the current mismatch persisting past this
  WP.
- `artifacts/cwv_integration/preregistration.md` + results (SAP v3 protocol
  reused verbatim) — the confirmation round for any default-on promotion.

**Test.** determinism of the NLI backend under pinned model + seeds (or the
probe variant, Kossen et al. 2024, if NLI cannot be made deterministic
offline — in which case the fingerprint backend stays default and the doc says
why); regression: no reported number changes without its artifact changing.

**Code.** No new backend module — activate the existing `NLISemanticBackend`
(`remora/semantic_entropy.py`; note `remora/selective/pvd.py` also defaults to
the fingerprint backend and must be in any parity sweep). CWV:
`remora/cascade/cwv.py` wired into `ConsensusGate`
(`remora/cascade/stages.py`) — there is no `remora/consensus/`; the reference
implementation to port is the isotonic-PAV calibration +
`conf_weighted_prediction` in `experiments/sap_v3_round.py`; check
`remora/correlation.py` `WeightedConsensus` and the uncalibrated
confidence-weighting in `remora/thermodynamics.py` before adding anything
parallel, and distinguish calibrated CWV from raw weighting. Flag:
`REMORA_CWV` parsed per the existing boolean-env convention (`{'1','true','yes'}`).

**Acceptance.** `NEGATIVE_RESULTS.md` §3 closed (or explicitly narrowed) with
a dated resolution note — kept in the file, resolved ≠ deleted, per
contributing rules.

**Verdict after grounding: start now (slice 1).** The WP targets the last
Active published negative finding of its class and every prerequisite for
slice 1 exists: ubuntu CI, pinned torch/sentence-transformers, implemented and
tested backend, liftable CWV reference. Slice 1 = one PR: a manual/nightly
ubuntu CI job with an `nli` extra that actually executes the NLI backend and
emits `results/se_backend_parity_smoke.json` — the first NLI-executed artifact
on disk, directly narrowing §3 around the WinError 4551 constraint. Full
parity (M–L, live-oracle cost) and the CWV confirmation round are scheduled
work, not this slice.

---

## RF-07 — Evidence sufficiency + adversarial corpus robustness `[evidence/RAG]` `[P2, effort M]`

**Gap (grounded).** Stage 3 (VerifierGate, `remora/cascade/stages.py`) folds
evidence insufficiency into the generic CHALLENGED judge outcome — there is no
distinct "the retrieved context cannot answer this" outcome
(`JudgeOutcome` = SUPPORTED/CHALLENGED/REFUTED/PARSE_ERROR only) — while the
evidence-router path already escalates on thin evidence
(`EvidenceLabel.INSUFFICIENT`, citation-coverage gate in
`remora/evidence/evidence_router.py`, zero-signal on empty retrieval). The WP
adds a first-class sufficiency outcome and an end-to-end benchmark, not a
from-scratch signal. On the adversarial side: no benchmark injects poisoned
passages into a retrieval corpus and measures decision flips — existing
adversarial RAG coverage (`artifacts/rag_adversarial_test.json`) uses
adversarial *questions* over clean sources, and unit tests cover passage
contradiction only. Single-document poisoning is a published, cheap attack.

**Already in the repo / adjacent surfaces.** The injection-ceiling work
(`NEGATIVE_RESULTS.md` §2) covers the *tool-result* `untrusted_context`
surface via `ToolResultScanner` — 53.3% hard-block / 80% detect / 0% benign FP
on 150 in-distribution attacks (`artifacts/aromer_injection_ceiling_v1.json`;
the in-distribution caveat is explicit and these numbers must not be cited as
general detection rates). RAG corpus poisoning is a different ingress surface;
scanner rules may be reused but results do not transfer. This WP advances the
published open item in `NEGATIVE_RESULTS.md` Active Finding 1: "Production
evidence retrieval validation (beyond MultiNLI proxy benchmark)". **Scope:**
the research-repo evidence path (`remora/evidence/`, local retrieval
backends). The live `remora-rag-oracle` worker and its hosted corpus are out
of scope (a separate WP; `remora/evidence/worker_client.py` documents an open
worker-drift item that must not be conflated with this).

**Literature.**

- Joren et al. (2025). *Sufficient Context: A New Lens on Retrieval Augmented
  Generation Systems.* ICLR. arXiv:2411.06037 — sufficiency classification,
  routed to abstention.
- Zou, Geng, Wang, Jia & Gong (2025). *PoisonedRAG.* USENIX Security.
  arXiv:2402.07867 — corpus-injection attacks flipping targeted answers.
- Chen et al. (2024). *AgentPoison: Red-teaming LLM Agents via Poisoning Memory
  or Knowledge Bases.* NeurIPS. arXiv:2407.12784.
- Gao et al. (2023). *ALCE: Enabling LLMs to Generate Text with Citations.*
  EMNLP. arXiv:2305.14627 — attribution-eval methodology for the citation path.

**Artifact.**

- `datasets/rag_poisoning_v1/` — deterministic fixture corpus: clean baseline +
  k poisoned variants per query (single-doc and multi-doc), built as poisoned
  variants of `datasets/remora_knowledge_v1/static_rag/`; ships `manifest.json`
  + `README.md` + `can_train=False` flags, mirroring
  `datasets/aromer_external_holdout_v1/`.
- `artifacts/evidence_sufficiency_v1.json` — sufficiency-signal
  precision/recall on a labeled slice; ABSTAIN-routing delta (versioned flat
  name per artifact convention; no number enters any doc until this exists).
- `docs/research/evidence_integrity.md` — per-document content hashes;
  `corpus:<doc_sha>` origin labels feed RF-02's provenance lattice (explicit
  dependency).

**Test.** `tests/test_rag_poisoning.py` — no committed single-document
poisoning flips an ACCEPT (target stated as a bound with CI, not "never");
`tests/test_sufficiency_routing.py` — insufficient-context fixtures route
ABSTAIN at ≥ pre-committed rate (extends `tests/test_evidence_router.py`, which
already asserts escalate-on-insufficient, rather than re-testing it).

**Code.** `remora/evidence/sufficiency.py` (signal + router hook — must extend
`EvidenceSignal`/`CriticalEvidenceRouter`, not introduce a parallel
sufficiency type) and `remora/evidence/corpus_integrity.py` (doc hashing,
quarantine labels).

**Acceptance.** Poisoning-robustness number enters the README only with the
fixture-corpus caveat attached, v2-benchmark style.

**Verdict after grounding: soon; the dataset slice can start any time.**
Slice 1 is measurement-only and needs no new `remora/` modules: build
`datasets/rag_poisoning_v1/`, run the *existing*
RAGEvidenceProvider → CriticalEvidenceRouter pipeline over clean vs poisoned
corpora, and emit `artifacts/evidence_sufficiency_v1.json` recording
escalate/abstain/accept deltas — showing where the existing coverage gate
already catches "cannot answer" and where it fails, which then scopes
`sufficiency.py`/`corpus_integrity.py` honestly (and may legitimately produce
a negative result for `NEGATIVE_RESULTS.md`).

---

## RF-08 — Audit anchoring: wire Merkle checkpoints to the live chains + external transparency log `[audit]` `[P0, effort S–M]`

**Gap (grounded — narrower than the draft assumed).** The checkpoint
primitives already exist and are tested: `remora/audit/merkle.py`
(`compute_merkle_root`, `sign_root`, `verify_signed_root`,
`export_daily_root`), `remora/audit/anchor.py` (`AuditAnchor`, HMAC-signed
anchor records, external-auditor CLI `scripts/verify_audit_anchor.py`),
`tests/test_audit_anchoring.py`; `docs/assurance/threat_model_v1.md` marks the
daily Merkle root anchor Implemented. The remaining gap: (a) checkpoints are
not wired into the per-tenant envelope chain
(`servers/api.py:_finalize_envelope_audit` / `remora/governance/tenant_chain.py`)
or the shadow/replay envelope chain (`remora/shadow/replay.py`
`verify_envelope_hash_chain`) — `compute_merkle_root` accepts only the legacy
`HashChainEntry` type; (b) no external transparency-log/WORM publishing exists
(roots land in local JSONL, which `merkle.py` itself warns "provides no
additional security"); (c) no committed sample checkpoint artifacts; (d) the
limitation is stated verbatim in `README.md` ("Tamper-evident, not
tamper-proof. The hash chain detects modification after the fact; preventing
it requires external append-only (WORM) storage not included here."), echoed
in `docs/02-evidence-and-claims.md`, `docs/08-security.md`, and
`ARCHITECTURE.md`. This WP is the closing vehicle for registered items:
remediation_register **REM-025** ("Durable audit integrity", NOT_STARTED) and
assurance-case defeater **D-7** — updating those rows is an acceptance
criterion, and the adversarial-review ROADMAP row for REM-025 follows. Timing
pressure: EU AI Act Art. 12 record-keeping obligations for high-risk systems
apply from Aug 2026; the compliance mapping already exists in
`docs/governance/eu_ai_act_nsm_mapping.md` (whose Art. 12 rows explicitly name
the WORM/RFC-3161 gap → REM-025).

**Literature.**

- Laurie, Langley & Kasper (2013). *Certificate Transparency.* RFC 6962 —
  Merkle-tree log construction + consistency proofs.
- Newman et al. (2022). *Sigstore: Software Signing for Everybody.* ACM CCS —
  Rekor transparency log.
- Torres-Arias et al. (2019). *in-toto: Providing farm-to-table guarantees for
  bits and bytes.* USENIX Security — attestation framing for the "who produced
  this decision record" question (pairs with the existing actor-binding work
  and the REM-021 CI attestation bundle, `scripts/generate_test_attestation.py`,
  which stays a distinct mechanism — no second attestation vocabulary).
- W3C (2025). *Verifiable Credentials Data Model v2.0.* Recommendation.
- (2026). *Proof-Carrying Agent Actions.* arXiv:2606.04104 — closest research
  framing: verifiable evidence attached per action.
- Regulation (EU) 2024/1689 (AI Act), Art. 12 — automatic recording of events
  over the system lifetime, high-risk obligations from Aug 2026.

**Artifact.**

- `docs/enterprise/audit-anchoring-guide.md` — checkpoint interval, root
  format, inclusion/consistency-proof verification procedure, threat-model
  delta (what anchoring adds over the bare chain, exactly). This exact path
  fixes a dangling reference: `remora/audit/merkle.py` already points to it.
- Compliance mapping: extend `docs/governance/eu_ai_act_nsm_mapping.md` and
  `docs/governance/nist_ai_rmf_mapping.md`; add
  `docs/governance/iso_42001_mapping.md` for the genuinely new ISO/IEC 42001
  part — all explicitly marked "mapping, not a conformity claim".
- `artifacts/audit_anchoring/sample_checkpoints.jsonl` — generated from the
  demo shadow log; a deliverable, not citable until committed.

**Test.** Extend `tests/test_audit_anchoring.py` (do not create a
near-duplicate `test_merkle_checkpoint.py`): chain-agnostic leaf adapter over
tenant-chain entries and DecisionEnvelope chains; single-bit tamper anywhere
in a checkpointed span → detected via recomputation; consistency proof between
checkpoint N and N+1; mock-anchor roundtrip (local file-based append-only log
stand-in; no network in `make test`).

**Code.** Extend `remora/audit/merkle.py` (or add
`remora/audit/checkpoint.py` for the chain-agnostic layer — not a second
"merkle" module): leaf adapters for `tenant_chain` entries and envelope
chains; checkpoint export hooked into `servers/api.py:_finalize_envelope_audit`
or a periodic hook over `TenantChain.verify_all`. Anchoring transport lives
outside `make test`: `workers/audit-anchor/` (kebab-case; "anchor" alone is
taken by the unrelated intent-anchor in `scripts/remora_anchor.py`) — a
Cloudflare Worker posting signed checkpoint payloads to R2 with
object-lock/WORM retention, Rekor as the public-log alternative. The chains
themselves are unchanged — this is strictly additive.

**Acceptance.** Limitations section rewrites "requires external WORM storage"
to "checkpointed Merkle roots anchored externally; see
docs/enterprise/audit-anchoring-guide.md" — with the residual caveat kept:
anchoring upgrades tamper-evident to tamper-*resistant* for post-checkpoint
history only; it does not make the writer honest at write time, and the WP
never claims "tamper-proof" (the claim ledger requires stating the distinction
every time). REM-025 and D-7 rows updated in the same change.

**Verdict after grounding: start now.** Promoted from the draft's P1: it
closes already-registered open findings (REM-025, D-7) plus a verbatim
README/paper limitation, and the first slice is genuinely S because the
primitives, signing, export, verification CLI, and tests all exist — the work
is leaf adapters, wiring, one committed sample artifact, and the guide doc
(which also fixes the dangling reference). The external worker is slice 2.

---

## RF-09 — External benchmark adapters: AgentDojo + MCPTox `[benchmarks]` `[P2, effort M]`

**Gap (grounded).** All primary benchmarks are internally authored *except*
AgentHarm (CLAIM-002: FAR 0.0%, Wilson 95% CI [0.00%, 1.81%], N=208 harmful +
208 benign, `results/external_benchmark_agentharm_v1.json`) — per
`docs/assurance/benchmark_audit_v1.md`, AgentHarm is the one external-dataset
exception. AgentDojo and MCPTox would add a second and third externally
authored dataset. **What this WP does and does not answer:** adapters widen
*dataset* independence; *evaluation-run* independence (external replication —
`README.md` Limitations, `NEGATIVE_RESULTS.md` §1) is a different evidence
level that internally-run adapters cannot close, and the README distinction
stays. AgentDojo is partially present already: `agentdojo==0.1.35` is pinned
in `requirements-lock.txt`, the dataset is a compendium ref under RES-005, and
`remora/toolcall/benchmark_v3.py` generates "AgentDojo-inspired" *synthetic*
injection instances — the real-dataset adapter is what is missing, and results
from the two must never be conflated. MCPTox has zero repo presence (pairs
with RF-01).

**Literature.**

- Debenedetti et al. (2024). *AgentDojo: A Dynamic Environment to Evaluate
  Prompt Injection Attacks and Defenses for LLM Agents.* NeurIPS D&B.
  arXiv:2406.13352.
- Wang et al. (2025). *MCPTox.* arXiv:2508.14925.
- Kutasov et al. (2025). *SHADE-Arena* — deferred; requires model-in-the-loop
  episodes that break the no-API-keys test contract. Revisit only with a
  recorded-episode replay design.

**Artifact.** `experiments/agentdojo/` and `experiments/mcptox/` package
directories mirroring `experiments/agentharm/` (preflight → probe → pilot →
full → score; score fails hard on missing baseline; secrets masked). Not
`eval_pack/` — that is the BYO-agent-logs shadow-mode pack. Never a top-level
module importable as `agentdojo` (it would shadow the pip package).
Pre-registered protocol docs per adapter; results reported cluster-level with
the template-vs-instance distinction the v2 postmortem forced
(`NEGATIVE_RESULTS.md` §17, `docs/assurance/statistical_analysis_plan.md`,
assurance-case defeater D-3: report the benchmark's own N-structure honestly,
whatever it is). Deliverable: an `mcptox` compendium id under RES-005 in
`docs/research/research_control_matrix_v1.yaml` + regenerated matrix.

**Test.** Deterministic fixture-episode tests, unmarked, running in
`make test` without benchmark dependencies or API keys (precedent:
`tests/test_agentharm_pipeline.py`); live network runs behind the `live`
marker or dedicated Makefile targets `agentdojo-benchmark` /
`mcptox-benchmark` (per-benchmark precedent — there is no `bench-external`
target, and `external-review` already means something else); a
rem014_gate-style structural test binding any committed result artifact to its
claim-register entry.

**Code.** Adapter shims translating benchmark episodes → REMORA envelope
stream; zero benchmark-specific logic inside `remora/` itself. Dependency
plan: an `agentdojo` optional extra in `pyproject.toml` following the
`agentharm` extra precedent (the lock already resolves agentdojo 0.1.35, so no
lockfile churn).

**Acceptance.** Numbers enter `EVIDENCE_OF_CAPABILITY.md` only with the
benchmark version pinned, the harness commit pinned, and the caveat that the
run is internally executed on externally authored tasks (a different claim
from external replication — the README distinction stays).

**Verdict after grounding: soon (after the Assurance Kernel Freeze).** Much of
the plumbing exists (the agentharm adapter pattern, the pinned dependency, the
compendium entry), nothing hard-blocks it, but it closes no published finding —
the gaps it superficially targets are about run independence, which it cannot
provide. First slice: the `experiments/agentdojo/` scaffold with committed
fixture episodes, a fail-hard scorer, offline pytest coverage, and a Makefile
target stub — no live run, no result artifact, no claims, nothing in the claim
register until a real run exists.

---

## RF-10 — Declared task–tool contracts: preconditions, effects, minimal frontier `[gating]` `[slice 1 shipped, remainder P1–P2, effort M]`

**Source appraisal.** Four externally published works motivate this WP. Each
was retrieved and its title, authors and abstract confirmed against arXiv on
2026-08-03 before being cited here; none of their reported numbers are
reproduced as REMORA results.

| Work | arXiv | What it shows | What REMORA takes |
|---|---|---|---|
| Ravindran & Deochake, *ToolGuardian: Declarative Security for AI Agent-Tool Interactions* | [2607.21835](https://arxiv.org/abs/2607.21835) | Separates tool *characterization* from the policy decision; reasons over capabilities, observed effects and task context with Answer Set Programming | The characterization/decision split, already realised as `ToolContract` + `goal_match`. ASP is **not** adopted: REMORA's engine is a frozen first-match table, and a solver in the decision path would replace an auditable artifact with a search |
| Babu & Iyer, *ToolChoiceConfusion: Causal Minimal Tool Filtering* | [2606.06284](https://arxiv.org/abs/2606.06284) | Precondition–effect contracts expose only tools that can advance the current state; "relevance is insufficient — a tool may be related while still premature" | The frontier concept, as an **advisory harness filter**, never as a gate. Their reported reduction (100 visible tools → ~1/step, ≈90% token cut over 102 tasks) is their result on their setup and is not a REMORA claim |
| Kamath et al., *Enforcing Temporal Constraints for LLM Agents* (Agent-C) | [2512.23738](https://arxiv.org/abs/2512.23738) | First-order-logic specs + SMT solving to block non-conformant actions during generation | The *ordering* requirement ("approve before close"), as declared `preconditions` on a contract. SMT is deferred: a deterministic session state machine covers the single-call case and is auditable without a solver in the loop |
| Guo et al., *Sample, Predict, then Proceed* (DyMo/SVS) | [2506.02918](https://arxiv.org/abs/2506.02918) | A trained dynamics model predicts post-action state and screens proposed calls | The predict-before-execute *shape* only. The model-trained part is explicitly refused as an authority: a generative state estimate must never establish SUPPORTED (see the module docstring) |

**Gap (grounded, 2026-08-03).** `CallCompatibility` (`compatibility.py`) has
carried five tri-state slots since it was defined. Three were populated:
`argument_roles_valid`, `argument_values_supported`, and — via
`goal_match.match_tool_to_intent`, wired at `evaluate.py:219` —
`tool_matches_goal`. Two were permanently `None` with the module docstring
recording why: "a guessed field is worse than an absent one". Those two are
exactly where the works above land.

**Slice 1 — shipped in this change.**

- `ToolContract` gains `state_delta` (declared post-state, dotted field →
  value) and `preconditions` (named facts that must hold first). Both default
  empty and round-trip through the registry JSON, so existing contracts are
  unaffected.
- A read contract that declares a `state_delta` is refused at construction,
  matching the existing refusal of `mutation=False` with a non-read effect: a
  self-contradictory declaration must not be resolvable while a call is
  pending.
- `remora/toolcall/routing/effect_prediction.py` supplies
  `expected_effect_matches`. It refutes three cases the label comparison in
  `goal_match` cannot see: a read request served by a tool declared to mutate,
  a change request served by a read-only tool, and a declared post-state that
  writes a resource the intent never named.
- It also **tightens** one case: a mutating contract with no declared
  `state_delta` is UNKNOWN, where `goal_match` alone returns SUPPORTED on the
  matching label. An undeclared write does not ride on a label.
- Policy wiring mirrors `tool_does_not_match_goal` exactly — established
  `False` → ABSTAIN (read) / ESCALATE (write); `None` and `True` fire nothing.
  `tests/test_effect_prediction.py` pins that an established `True` buys no
  autonomy and does not relax the critical-tier floor.

**Not implemented, and why.** These are registered here rather than left as
folklore:

- *No-op detection* ("close a work order that is already closed") needs
  field-level current state. `StateIndex` is a flat value set by deliberate
  design — a schema-aware state model "invites over-fitting to one dataset's
  shape". Adding one is a separate decision needing its own evidence.
- *Argument-bound delta templates* (`work_order.{id}.status`). The signature
  accepts `proposed_args` so this lands without an interface change; today a
  placeholder is left verbatim rather than half-bound.
- *`preconditions_met`.* The field is declarable now; the adjudicator is not
  written. It needs an authoritative fact set (approval records, session
  history), and inventing one would let a model's claim of "approved" satisfy
  an approval gate. This is the Agent-C slice, and it is the natural next one.
- *Minimal causal tool frontier.* Advisory harness work, not a gate. It has no
  effect on any decision REMORA makes and therefore cannot be justified as
  safety work; it belongs with the agent hook.

**Verdict: slice 1 done, `preconditions_met` next, frontier after.** The
sequencing is not the papers' — it is REMORA's: the two authorities that fill
existing policy-contract slots come before any harness feature, because only
they change what the system refuses.

---

## 10. Sequencing rationale (post-grounding)

**P0 — starts now, each closes something already published:**

- **RF-04** attacks the FBR=100% corner the paper itself names "an explicit
  target for REMORA's calibration roadmap", with the gap-audit's AI-control
  row graded yellow; all in-repo dependencies exist, and the
  new-protocol/new-claim scoping resolves the CLAIM-002 import constraint.
- **RF-06** targets the last Active published negative finding of its class
  (`NEGATIVE_RESULTS.md` §3) and its first slice is unblocked today via CI
  Linux (the WinError 4551 constraint is local-only).
- **RF-08** closes registered items REM-025 and defeater D-7 plus a verbatim
  README limitation, and grounding showed the primitives already exist — the
  remaining work is wiring, one artifact, and a guide doc that fixes a
  dangling reference. The Aug 2026 AI Act Art. 12 date makes it timely.

**P1 — scheduled, not idle:** RF-01 lands as prerequisite hardening with
MCP/external tool fronting (REM-024/REM-030 residual; after the Assurance
Kernel Freeze #35/#37/#38/#39, since open issue #37 touches the same execution
path). RF-02 slice 1 (carry `argument_tainted` through `from_record` + the
envelope) fixes a live integration hole in the just-shipped v4 taint floor and
is small; the full CaMeL-class lattice stays P2 behind the interception probe.

**P2 — architecture-deepening:** RF-07's dataset slice is measurement-only and
can start opportunistically; the module work follows what the measurement
shows. RF-09 fits immediately after the freeze as the next external-dataset
step, with the honest caveat that it widens dataset independence only.

**P3 — deferred on evidence:** RF-05's premise (drift-harden τ*) was
invalidated — the temperature selector was falsified in the pre-registered
SAP v3 round and the anytime-valid monitoring half is substantially shipped;
it re-enters when the rebenchmark protocol validates a selector. RF-03's
declarative-policy half is largely covered by the OPA/Rego layer; the
formal-semantics + trajectory-FSM residual closes no published finding and
should wait for the Lyapunov `abort_window` semantics to stabilize.

**Changes vs. the pre-grounding draft:** RF-01 P0→P1 (no live attack surface
until external tool fronting; AT-04 published as Covered), RF-05 P1→P3
(premise falsified), RF-08 P1→P0 (mostly built; closes REM-025/D-7), RF-03
unchanged P3, all grounded in the "Already in the repo" subsections above.

## 11. Considered and not included (with reasons)

- **Hardware TEE attestation** (AgenTEE-class, 2026). Wrong layer for a
  research repo without a hardware story; revisit only if a deployment partner
  supplies the platform.
- **zkML / verifiable inference.** Proof costs remain orders of magnitude from
  practical for envelope-rate workloads; the Merkle+transparency-log design
  (RF-08) covers the auditable-record need.
- **Blockchain anchoring.** Rekor/WORM achieves the append-only property with
  none of the operational cost.
- **Fleet-level / institutional governance frameworks** (2026). Different
  abstraction: they govern populations of agents; REMORA governs one gate. Cite
  as related work in the paper; do not import.
- **Fine-tuning-based injection robustness.** Out of scope by design — REMORA's
  premise is model-agnostic system-layer control; training-side defenses are
  complementary, not components.
- **SHADE-Arena as a first-class benchmark.** Breaks the deterministic
  no-API-keys test contract (see RF-09 note).

---

Every WP above is a proposal. The claim-hygiene rule applies to this document
too: if a WP ships and misses its pre-committed target, the result goes to
`NEGATIVE_RESULTS.md` with the number and the caveat, and this roadmap gets a
dated resolution note rather than a silent edit.
