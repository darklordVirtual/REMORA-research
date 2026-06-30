# REMORA Independent Review Protocol v1

**Version:** 1.0  
**Date:** 2026-06-30  
**Gate:** REM-021 (Independent human review — required before leaving SHADOW_ONLY)  
**Status:** NOT_STARTED  
**Contact:** Stian Skogbrott — support@luftfiber.no

This document is the external reviewer package for REM-021. It defines scope,
questions to answer, the scorecard, conflict-of-interest requirements, and
output artifacts. When an external reviewer completes this protocol, they commit
their signed report as `docs/assurance/independent_review_v1.md` and REM-021
closes.

---

## 1. Purpose and Scope

REMORA is a pre-execution governance framework for AI agents. This review
assesses whether:

1. The decision engine logic is sound and correctly implements the stated policy
2. The PDP/PEP architectural separation holds under adversarial conditions
3. The historical regression proof (REM-019) corpus construction is valid
4. The AgentHarm external benchmark (REM-014) was run and scored honestly
5. Claim hygiene across README and paper matches committed artifacts

This is a **methodology and claims review**, not a full security audit or
deployment certification. The reviewer does not certify REMORA as production-safe;
they verify that the stated methodology is correctly implemented and the claims
accurately reflect the evidence.

### Out of scope

- Live deployment testing (REMORA is SHADOW_ONLY)
- Cryptographic audit of the hash chain
- Full code security audit (see REM-022 for RBAC)
- External replication (re-running experiments from scratch)
- Review of AROMER learning dynamics beyond what is needed for safety claims

---

## 2. Reviewer Eligibility

The reviewer MUST satisfy ALL of the following:

- Not a current or recent (< 12 months) employee, contractor, or collaborator of
  Stian Skogbrott or Luftfiber AS
- Not a contributor to this repository (no commits, no PR reviews)
- Has expertise in at least ONE of: AI safety evaluation, software verification,
  policy-as-code systems, or statistical methods for ML benchmarks
- Signs the conflict-of-interest declaration in Section 8 before starting

---

## 3. Review Materials

The reviewer should read the following documents before beginning:

### Primary documents

| Document | Path | Purpose |
|---|---|---|
| Repository overview | README.md | System description, claims summary, limitations |
| Architecture | docs/01-architecture.md | Pipeline stages, decision flow |
| Evidence and claims | docs/02-evidence-and-claims.md | Headline claims with artifact pointers |
| Claim register (human) | docs/claim_register.md | Full claim taxonomy and evidence levels |
| Claim register (machine) | docs/assurance/claim_register_v1.yaml | Machine-readable claim status |
| Claim hygiene rules | docs/claim_hygiene.md | What REMORA may and may not claim |
| Negative results | NEGATIVE_RESULTS.md | All documented failures and gaps |
| Release gates | docs/assurance/release_gates.md | P0 safety gates and deployment gates |
| Remediation register | docs/assurance/remediation_register.yaml | All resolved and open items |
| Statistical analysis plan | docs/assurance/statistical_analysis_plan.md | Pre-registered hypotheses |
| CLAUDE.md | CLAUDE.md | Working agreement and claim hygiene rules |

### Key artifacts

| Artifact | Path | Claim |
|---|---|---|
| AgentHarm benchmark result | results/external_benchmark_agentharm_v1.json | CLAIM-002: FAR=0% on N=208 |
| Regression proof | results/false_accept_regression_v1.json | CLAIM-003: FAR=0% on N=167 |
| Toolcall v2 result | results/toolcall_benchmark_v2_results.json | CLAIM-001: FAR=0% on N=700 |
| Blinded v3 result | results/toolcall_blind_v3_results.json | CLAIM-010: leakage_free=True |
| Selective holdout | results/selective_n500_holdout_results.json | CLAIM-004: 88.0% at N_accepted=25 |
| M1 clean-signal | results/toolcall_m1_clean_signal.json | M1 fix: leakage not load-bearing |

### Source code modules

| Module | Path | Review focus |
|---|---|---|
| Decision engine | remora/policy/decision_engine.py | Stage ordering, ESCALATE/VERIFY/ABSTAIN/ACCEPT logic |
| Observation schema | remora/policy/observation.py | schema_valid=None default, taint tracking |
| Enforcement gate (PEP) | remora/enforcement/gate.py | Token verification, fail-closed behavior |
| Token (PDP output) | remora/enforcement/token.py | HMAC signing, observation hash binding |
| REMORA gate (tool-call) | remora/toolcall/remora_gate.py | M1 fix: is_unsafe_if_executed absent |
| AST leakage detector | scripts/check_no_evaluation_leakage.py | CI guard against leakage re-introduction |

---

## 4. Questions to Answer

The reviewer must answer each question with: YES / NO / PARTIAL / NOT_ASSESSED,
followed by supporting evidence or a finding description.

### Section A: Decision Engine Correctness

**A1.** Does the decision engine correctly enforce the priority ordering
ESCALATE > ABSTAIN > VERIFY > ACCEPT? Specifically, can any adapter or
downstream code reduce an ESCALATE to VERIFY or ACCEPT?

**A2.** Does Stage 1 (hard-block policy invariants) execute before Stage 2
(multi-oracle consensus) in all code paths, including edge cases?

**A3.** Is `schema_valid=None` treated as "unknown" (not "safe") for all
mutating actions? Does a None schema_valid block the ACCEPT path?

**A4.** Does the tainted-argument gate correctly prevent auto-ACCEPT when
untrusted-derived arguments are present?

**A5.** Does the adversarial input detection (`_detect_adversarial_input`)
cover the relevant attack surface? (See NEGATIVE_RESULTS.md §2 for known gaps.)

### Section B: PDP/PEP Architectural Separation

**B1.** Does the PolicyDecisionToken carry an HMAC-SHA256 signature that
correctly binds the PDP decision to the specific observation? Can a token
for action A be replayed to authorize action B?

**B2.** Does the EnforcementGate (PEP) fail closed on:
  (a) a tampered action,
  (b) a forged signature,
  (c) an observation hash mismatch,
  (d) an unsigned token in strict mode?

**B3.** Does the PDP/PEP separation prevent a caller from bypassing the PDP
decision by directly invoking the execution path?

### Section C: REM-019 Regression Proof Validity

**C1.** Is the corpus of 167 historical false-accept episodes drawn from a
documented source (AROMER D1 `decision_quality='false_accept'`)? Is the
source trustworthy and not author-controlled at evaluation time?

**C2.** Are the two excluded episodes (aradhye-0060, caizhitech-1059)
legitimately excluded? Does the rationale hold under scrutiny?

**C3.** Is the VERIFY floor policy change (for risk_tier=high/critical)
conservative by construction — i.e., can it only decrease false accepts,
never increase them?

**C4.** Does `results/false_accept_regression_v1.json` match the stated
N=167, blocked=167, FAR=0.0% claim?

### Section D: REM-014 AgentHarm Benchmark Validity

**D1.** Does `results/external_benchmark_agentharm_v1.json` match the stated
N=208, blocked=208, FAR=0.0% claim?

**D2.** Is there credible evidence that the AgentHarm dataset
(`ai-safety-institute/AgentHarm`, arxiv:2410.09024) was not present in
REMORA's training corpus? What is the evidence for external validity?

**D3.** Is the FBR=100% on benign variants explained and plausible? Does it
indicate a problem with the benchmark design that should be disclosed?

**D4.** Is the result correctly framed as a hard-block (Stage 1) result, NOT
as evidence for the multi-oracle consensus machinery?

### Section E: Claim Hygiene

**E1.** Does the README cite the 88.0% selective accuracy result with its full
Wilson CI [70.0%, 95.8%] and the N_accepted=25 caveat?

**E2.** Does the README correctly distinguish simulator-scoped results from
field deployment claims? Is the "deterministic simulator" qualifier present?

**E3.** Are all negative results (NEGATIVE_RESULTS.md) accurately summarized
in README and paper, without any being weakened, hidden, or removed?

**E4.** Does the README use "reduces unsafe" or equivalent language for the
v2 benchmark, qualified with "simulator-scoped"?

**E5.** Are the AII/AROMER metrics correctly described as experimental and
not cited as safety proofs for the core governance system?

---

## 5. Scorecard

Complete this table after answering Section 4 questions.

| Question | Answer | Finding (if NO/PARTIAL) |
|---|---|---|
| A1 | | |
| A2 | | |
| A3 | | |
| A4 | | |
| A5 | | |
| B1 | | |
| B2 | | |
| B3 | | |
| C1 | | |
| C2 | | |
| C3 | | |
| C4 | | |
| D1 | | |
| D2 | | |
| D3 | | |
| D4 | | |
| E1 | | |
| E2 | | |
| E3 | | |
| E4 | | |
| E5 | | |

### Overall verdict

Choose one:

- **PASS**: All questions answered YES, or PARTIAL with documented minor findings
  that do not affect safety claims. REM-021 may be closed.
- **CONDITIONAL PASS**: Specific items require author response before close.
  List findings in Section 6.
- **FAIL**: One or more critical findings that require code or documentation
  changes before REM-021 can be closed. List findings in Section 6.

---

## 6. Findings and Recommendations

List each finding with:

```
Finding ID: RV-XXX
Question: [A1/B2/etc]
Severity: [CRITICAL / MAJOR / MINOR / INFORMATIONAL]
Description: [what was found]
Evidence: [file, line number, or artifact]
Recommendation: [what must change for this finding to be resolved]
```

---

## 7. Scope Limitations

The reviewer acknowledges the following inherent scope limitations:

1. **Simulator-scoped benchmarks.** All key benchmarks (`toolcall_benchmark_v2`,
   `selective_n500`, `selective_trust_curve`) are deterministic synthetic
   simulations. This review cannot validate field-deployment safety.

2. **No external replication.** The reviewer is assessing methodology and
   documentation consistency, not independently re-running experiments. Claimed
   results are taken from committed artifacts; spot-checks against source code
   are performed but full reproduction is not within scope.

3. **AROMER is not primary scope.** The review covers AROMER claims only
   to the extent they are cited in README or paper safety claims. Full
   review of AROMER learning dynamics is out of scope.

4. **No cryptographic audit.** The hash chain and token signing are reviewed
   for logic correctness but not for cryptographic security (e.g., key
   management, side-channel resistance).

5. **No RBAC audit.** RBAC is covered by a separate gate (REM-022) and is
   out of scope for this review.

---

## 8. Conflict-of-Interest Declaration

The reviewer must sign and date this declaration before beginning:

---

I, [REVIEWER NAME], declare that:

1. I have no current or recent (< 12 months) employment, contracting, or
   collaboration relationship with Stian Skogbrott or Luftfiber AS.
2. I have not contributed code, reviews, or documentation to the
   `darklordVirtual/REMORA-research` repository.
3. I have no financial interest in the outcome of this review.
4. I have disclosed any potential conflicts of interest to the REMORA team
   before accepting this review.
5. I understand that this review assesses methodology and claim hygiene, not
   production certification.

**Signature:** _________________________  
**Date:** _______________________________  
**Institution/affiliation:** ____________

---

## 9. Output Artifact

When complete, the reviewer commits (or provides for committing) their filled-out
scorecard and findings as:

```
docs/assurance/independent_review_v1.md
```

This file MUST include:
- Completed scorecard (Section 5)
- All findings (Section 6, even if empty)
- Signed conflict-of-interest declaration (Section 8)
- Overall verdict

Upon commit of this artifact with a PASS or CONDITIONAL PASS verdict (with all
conditional items resolved), the REMORA team may close REM-021.
