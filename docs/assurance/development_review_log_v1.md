# REMORA Engineering & Review Log

*A single, honest record of how this repository was built and hardened, for a
reviewer who wants to see the engineering discipline, not just the result.*

**Current head reflects:** research-grade assurance control plane, deployment
status `SHADOW_ONLY`. Every claim below links to an artifact, a test, or a
file:line. Where something is unproven, this document says so in the same
sentence. That discipline, keeping each caveat next to its claim, is the
point of the whole repository, so it is the point of this log too.

---

## 1. Where the project stands (verifiable state)

| Dimension | State | How to verify |
|---|---|---|
| Test suite | 3,514 tests, 0 failing (from 3,301 at the start of the hardening cycle: **+213**) | `pip install -e ".[dev,causal,api]" && make test` |
| CI | Green on 3 Python versions (3.12/3.13/3.14) + pinned-OPA conformance + claim-provenance gate | GitHub Actions, every push |
| Result artifacts | 78 committed under `results/`; every headline number is reproducible offline | see §6 |
| Remediation items | 22 of 30 tracked REM-items DONE; **REM-021 (independent review) is the sole open production gate** | [`remediation_register.yaml`](remediation_register.yaml) |
| Capability wiring | 12 capabilities on an explicit six-rung ladder; **nothing claims `ENFORCED_PRODUCTION` or `EXTERNALLY_VERIFIED`** (a CI-enforced invariant) | [`capability_register_v1.yaml`](capability_register_v1.yaml), `tests/test_capability_register.py` |
| Deployment status | `SHADOW_ONLY`, unchanged, by design, until REM-021 closes | [`release_gates.md`](release_gates.md) |

The honest one-line summary: **a credible, executable reference architecture
for policy-governed agent assurance, hardened through eight external review
rounds into testable invariants. It is not a production-certified enforcement
product, and it does not claim to be one.**

---

## 2. The review-driven development arc

The repository's strongest signal is not any single feature; it is that every
round of external critique was converted into a *testable invariant*, and that
the process rejected bad findings as rigorously as it accepted good ones.

| Round | Focus | What it became |
|---|---|---|
| 1–2 | OPA policy parity | `OPAContext` exports the full decision-path contract; `tests/test_opa_parity.py` scans the engine source and fails CI if a new guard reads an unexported field |
| 3 | Decision monotonicity over adapters | `hard_guard_floor()` as one source of truth; OPA results floored, tightened-only |
| 4 | A2A trust chain | per-link signatures, principal-bound `RegisteredKey`, replay guard, payload binding, `tests/test_a2a_envelope.py` |
| 5 | Token replay, RBAC contract, identity | mandatory token expiry + `jti` one-time consumption; single role vocabulary; audit identity bound to the authenticated principal |
| 6 | Partition & stale approvals | degradation ladder G0–G4 + approval-freshness re-gate (REM-032/033) |
| 7 | Startup ordering, execution RBAC | actor-map init order; `execute` capability; profile approval role |
| 8 | End-to-end wiring | atomic per-tenant audit chain + durable adapters (REM-034); the full `/v1/execution/*` state machine (REM-035); concurrency safety (REM-036) |
| Ultra | Adversarial multi-agent code review | 6 verified correctness bugs fixed; 2 false positives rejected; a new AROMER result measured |

Each round's fixes are in the git history with the finding they answer, and
each carries a regression test. The gate register's elevation record
([`release_gates.md`](release_gates.md)) preserves the decisions, including the
ones that were *not* clean.

---

## 3. New capabilities delivered this cycle

All artifact- and test-backed. Wiring status is authoritative in
[`capability_register_v1.yaml`](capability_register_v1.yaml).

- **End-to-end execution state machine** (`servers/execution_api.py`,
  REM-035): `assess → ACCEPT token | VERIFY/ESCALATE queue → approve → fresh
  re-gate → one-time PEP grant`, every transition on the audit chain. The
  exact tool-call payload is hashed at the API boundary; a changed argument is
  refused by binding; a world that turned riskier voids the approval.
- **Atomic, durable per-tenant audit chain** (`remora/governance/tenant_chain.py`,
  REM-034): `entry_hash` covers predecessor, tenant, sequence and timestamp
  with an injective separator; `SQLiteTenantChain` (restart-proven, fork-free
  under a 100-append race) and `PostgresTenantChain` (`SELECT FOR UPDATE`);
  `verify()` checks the HMAC signature. This is the repo's one
  `PERSISTED_ATOMIC` capability.
- **Partition resilience** (`remora/governance/degradation.py`,
  `review_queue.py`, REM-032/033): recorded G0–G4 mode ladder; unattended
  reviews expire to ABSTAIN; approvals carry mandatory bounded expiry and are
  re-gated against the fresh world at execution.
- **AROMER cross-domain transfer, measured** (`remora/aromer/evals/cross_domain_transfer.py`,
  CAP-012): an abstract `(action_type × risk_tier)` harm prior, evaluated
  leave-one-domain-out, **83.8% transfer accuracy (109/130 across 10
  domains)**, artifact `results/aromer_cross_domain_transfer_v1.json`. Honest
  scope: this evidences the *capability* offline; it does **not** clear the
  live worker gate, which still shows `TRANSFER_UNMEASURED` until organic
  cross-domain traffic exists ([`../../NEGATIVE_RESULTS.md`](../../NEGATIVE_RESULTS.md) §16).

---

## 4. Engineering-rigor highlights (what should earn trust)

These are the moments where the process behaved the way you want a
safety-critical codebase's process to behave.

1. **It rejected false positives.** The adversarial multi-agent review flagged
   39 findings. Two ("FALSE_BLOCK outcomes discarded", "oracle bandit credited
   with fabricated signal") were verified against the actual code and found to
   be **already handled**, and were deliberately *not* "fixed". Verifying
   before acting is the discipline; a fix applied to working code is a
   regression waiting to happen.

2. **It caught its own supply-chain mistake.** A CI error message named a
   package `httpx2`; it was added uncritically, then flagged by security review
   as a likely typosquat. It was replaced with the legitimate `httpx`, the
   single install (a `contents:read` CI job with no secrets) assessed for
   exposure, and the incident used as the argument for hash-locked installs
   (REM-037).

3. **A gate refused to self-close.** REM-020's closure tooling found two
   conflicting "canonical" criteria (7-day vs 30-day) and **refused to close
   the gate** until the owner reconciled them, rather than silently picking
   one. The conflict, the reconciliation, and the fail-closed tooling run are
   all in the elevation record.

4. **A documentation pipeline that never ran was found and fixed.** The LaTeX
   auto-compile workflow triggered on `main`; the repo uses `master`, so the
   committed PDF had silently frozen. Both the trigger and the commit condition
   were corrected, and the title page now states content-date vs compile-date
   explicitly so a reviewer checking PDF metadata is never misled.

5. **Claims are machine-checked against artifacts.** `make check-claims` and
   the CI claim-provenance gate fail the build if a number appears without its
   backing artifact. The capability register's `SHADOW_ONLY` invariant is a
   test: nothing can silently claim production or external-verification status.

---

## 5. What is proven, what is scoped, what is open

Stated as three columns because conflating them is the failure mode this whole
repository exists to prevent.

**Proven (artifact + test):** zero false accepts on the blinded internal
benchmark (N=700) and an independent external harmful-scenario set (n=208, FAR
0.0%, Wilson upper 1.81%); the decision engine's hard-guard floor and its
28 mutation tests; OPA policy parity and monotone flooring; the A2A trust
chain, token replay protection, and the execution state machine's re-gate and
one-time consumption; the atomic durable audit chain; 83.8% offline
cross-domain transfer.

**Scoped (reference implementation, deployment work stated):** in-process
review-queue and jti-consumption stores (durable multi-node needs the shipped
DDL adapter + external store); symmetric-HMAC A2A signatures (production wants
JWS/COSE + trust anchors); the OPA reference policy passes safety-parity, not
full strict equivalence. Each of these is recorded with its exact boundary in
the capability register.

**Open (needs a person or an environment I cannot substitute):** REM-021
independent human review (the sole remaining production gate); external
benchmark replication; a shadow pilot against real agent logs; the remaining
REM-037 CI items (Linux lockfile, hash-locked installs); the durable-adapter
backlog REM-024–031 (mandatory PEP, external anchoring, DB-enforced tenant
isolation, supply-chain, HA, SIEM, tool-interception validation, GDPR/AI-Act
pack).

---

## 6. Reproduce every headline number

No number in this repository requires trusting the author. From a clean clone:

```bash
pip install -e ".[dev,causal,api]"
make test                                   # 3,514 tests, no keys, ~60s
python scripts/demo_industrial_maintenance.py   # the autonomy boundary, live engine
python experiments/end_to_end_n500_v3.py        # 0.8878 selective accuracy (claim 3)
python experiments/evaluate_toolcall_benchmark_v2.py  # unsafe=0.0000 (claims 1-2)
python scripts/run_cross_domain_transfer.py     # 83.8% cross-domain transfer
make audit                                       # lint + tests + claim consistency
```

Regenerated result artifacts are byte-identical to the committed ones, the
determinism is itself part of the evidence. Full reproduction guide:
[`../06-reproducibility.md`](../06-reproducibility.md).

---

*This log is maintained as part of the assurance corpus. It is descriptive, not
promotional: if it ever reads as more confident than the artifacts support,
that is a defect to file, not a feature.*
