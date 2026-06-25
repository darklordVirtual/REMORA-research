# REMORA × OWASP GenAI Top 10 Security Mapping

**Status:** internal mapping — not externally audited.
**Companion documents:**
- [`enterprise/threat-model.md`](../../enterprise/threat-model.md) — full threat narrative and controls
- [`enterprise/policy-model.md`](../../enterprise/policy-model.md) — OPA policy gates
- [`remora/agent_hook/`](../../remora/agent_hook/) — runtime hook implementation

The [OWASP Top 10 for Large Language Model Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
defines the current reference standard for LLM application risks.
This document maps each risk to REMORA's implemented controls, gaps, and
test coverage so that a security reviewer can assess coverage without
reading the full codebase.

---

## LLM01 — Prompt Injection

**Risk:** Malicious content in user input or retrieved documents instructs
the model to ignore policy, exfiltrate data, or execute harmful actions.

| Control | Implementation | Test |
|---|---|---|
| PreToolUse hook AST guard | `remora/agent_hook/hook.py`, `remora/safety/` — blocks shell injection patterns before execution | `tests/test_agent_hook.py`, `tests/test_shell_ast.py` |
| Retrieved text treated as data, not instruction | `ConsensusGate` prompt construction separates context from instructions | `tests/test_cascade.py` |
| Injection-indicator escalation | `enterprise/threat-model.md §1` — escalate on detected patterns for medium+ tiers | `tests/test_toolcall_v2_results.py` |
| Audit log of detection | Injection pattern stored in audit ledger | `enterprise/audit-ledger-schema.sql` |

**Gap:** REMORA does not yet run a dedicated NLI/semantic entailment model to
detect sophisticated indirect injection.  This remains a "requires external
replication" item in `docs/claim_register.md`.

---

## LLM02 — Insecure Output Handling

**Risk:** Model output is passed downstream without validation — e.g., into
SQL queries, shell commands, or rendered HTML.

| Control | Implementation | Test |
|---|---|---|
| Tool-call schema validation | `remora/toolcall/`, `remora/policy/` — validates tool args against JSON schema before execution | `tests/test_toolcall_v2_results.py` |
| Allowlist-only tool execution | `enterprise/risk-profiles.yaml` defines per-tier permitted tools | `tests/test_toolcall_v2_results.py` |
| Dry-run simulation before mutable actions | `enterprise/threat-model.md §3` | `tests/test_agent_hook.py` |

**Gap:** No HTML-output escaping layer yet; REMORA is an API/agent system,
not a web renderer, but downstream rendering must be handled by the integrator.

---

## LLM03 — Training Data Poisoning

**Risk:** Compromised training data causes the model to output unsafe or
misleading content.

| Control | Implementation | Test |
|---|---|---|
| Multi-oracle consensus | Three independent model families reduce single-model poisoning risk | `tests/test_cascade.py` |
| OracleDiversityTracker | Monitors pairwise correlation; warns when swarm converges (rho > 0.60) | `tests/test_cascade.py::TestCascadeEngineRuntimeWiring` |
| Independent judge verification | Stage 3 LLM judge from a different model family | `tests/test_cascade.py::TestVerifierGate` |

**Gap:** No mechanism to detect or mitigate data-poisoning in the retrieval
corpus; source allowlisting is the primary control.

---

## LLM04 — Model Denial of Service

**Risk:** Expensive or malformed prompts exhaust compute or API budget.

| Control | Implementation | Test |
|---|---|---|
| `budget_oracle_calls` cap | Hard cap on total oracle calls per request; returns VERIFY on exhaustion | `tests/test_cascade.py` |
| Stage short-circuit | Pipeline stops as soon as a terminal verdict is reached | `tests/test_cascade.py::TestFastGate` |
| Tenant isolation | `enterprise/architecture.md` defines per-tenant rate limiting | N/A (infrastructure-level) |

---

## LLM05 — Supply Chain Vulnerabilities

**Risk:** Compromised model weights, dependencies, or deployment artifacts.

| Control | Implementation | Test |
|---|---|---|
| Pure Python core | No compiled extensions; `pyproject.toml` pins dependency versions | `make audit` |
| Signed artifacts | `CITATION.cff`, `artifacts/README.md` document artifact provenance | `scripts/check_artifacts_exist.py` |
| Deterministic benchmarks | Locked benchmark artifacts (`artifacts/benchmark_n500_locked.json`) allow offline verification | `artifacts/reproduce.sh` |

---

## LLM06 — Sensitive Information Disclosure

**Risk:** Model leaks PII, credentials, or confidential data in its output.

| Control | Implementation | Test |
|---|---|---|
| File risk classifier | `remora/safety/` — detects secret patterns (API keys, private keys, tokens) before tool execution | `tests/test_agent_hook.py` |
| Tool arg redaction in audit | Audit ledger stores tool args but should redact secrets in production (see runbook) | `enterprise/audit-ledger-schema.sql` |
| Context isolation | Retrieved evidence is kept separate from the model's instruction context | `remora/cascade/stages.py` |

**Gap:** No automated PII detection in free-form model output; this requires
a dedicated NER/PII classifier at the output layer.

---

## LLM07 — Insecure Plugin Design

**Risk:** Plugins or tools expose excessive API surface to the model.

| Control | Implementation | Test |
|---|---|---|
| Policy gate + OPA | `remora/policy/` — all tool calls evaluated against OPA policy before execution | `enterprise/policy_as_code_example.yaml` |
| Risk-profile allowlist | `enterprise/risk-profiles.yaml` defines per-tier allowed tool actions | N/A |
| Default-deny | `enterprise/threat-model.md` — `ABSTAIN` on missing policy | N/A |

---

## LLM08 — Excessive Agency

**Risk:** The agent takes unintended or irreversible real-world actions.

| Control | Implementation | Test |
|---|---|---|
| Autonomy degradation | `remora/governance/` — confidence-based autonomy limits; critical actions require human approval | `tests/test_agent_hook.py` |
| Human approval workflow | `enterprise/human-approval-workflow.md` — RBAC, two-person rule for critical tier | N/A |
| Abstain/escalate routing | `CascadeEngine` returns `ESCALATE` on high uncertainty or policy violation | `tests/test_cascade.py::TestCascadeEngineRuntimeWiring` |
| Long-running drift detection | Lyapunov-based `V(t)` monitoring in `remora/lyapunov.py` | `tests/test_agent_hook.py` |

---

## LLM09 — Overreliance

**Risk:** Users trust model output without verification, especially on
high-stakes decisions.

| Control | Implementation | Test |
|---|---|---|
| Selective abstention | REMORA refuses to answer rather than guess when uncertainty is too high | `tests/test_selective_trust_curve.py` |
| Confidence calibration (PlattScaler) | Calibrated probabilities prevent overconfident outputs | `tests/test_cascade.py::TestCascadeEngineRuntimeWiring` |
| Uncertainty decomposition | Epistemic vs. aleatoric breakdown tells the user *why* the system is uncertain | `tests/test_uncertainty_decompose.py` |
| VERIFY verdict | Explicitly routes ambiguous answers to human review rather than forcing a choice | `tests/test_cascade.py` |

---

## LLM10 — Model Theft

**Risk:** Adversarial queries extract model weights, training data, or
system prompt contents.

| Control | Implementation | Test |
|---|---|---|
| System prompt isolation | REMORA constructs prompts programmatically; system instructions are not user-accessible | Architecture boundary |
| Audit trail | All oracle calls logged with question hash (not cleartext by default) | `enterprise/audit-ledger-schema.sql` |

**Gap:** REMORA is an application layer, not a model provider.  Actual model
extraction protection must be implemented at the inference infrastructure level.

---

## Coverage Summary

| OWASP Risk | Controls | Status |
|---|---|---|
| LLM01 Prompt Injection | AST guard, hook, audit, escalation | Partially implemented; no semantic injection detection |
| LLM02 Insecure Output | Tool schema validation, allowlist, dry-run | Implemented for tool calls; not for free-form text rendering |
| LLM03 Training Data Poisoning | Multi-oracle consensus, diversity tracking, judge | Partially mitigated; no corpus poisoning detection |
| LLM04 Model DoS | Budget cap, short-circuit, tenant isolation | Budget cap implemented; tenant isolation is infra-level |
| LLM05 Supply Chain | Pure Python, pinned deps, signed artifacts | Implemented at code level; infra signing is deployer responsibility |
| LLM06 Sensitive Disclosure | Secret pattern detection, redaction, context isolation | Partial; no PII detection in output text |
| LLM07 Insecure Plugin | Policy gate, OPA, allowlist, default-deny | Implemented |
| LLM08 Excessive Agency | Autonomy degradation, human approval, ESCALATE, drift detection | Implemented |
| LLM09 Overreliance | Selective abstention, PlattScaler, uncertainty decomposition, VERIFY | Implemented |
| LLM10 Model Theft | Prompt isolation, audit trail | Application-layer only; model-layer is out of scope |

**Overall posture:** REMORA addresses 8/10 OWASP GenAI risks at the
application layer.  LLM03 (training data poisoning detection in corpus) and
LLM06 (PII in free-form output) remain partial gaps requiring additional
tooling outside REMORA's current scope.
