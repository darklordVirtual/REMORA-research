# How do I reproduce every result from scratch?

Every headline result has an exact command and expected output file. Run `make test`
(or, with no `make` installed, `python -m pytest tests/ -q`) first to confirm the
environment is intact, then run the specific target below. Every `make` target here is
a thin wrapper over a `python` command; run `make help` to list them, or read the
recipe in the `Makefile` to get the exact `python`/`python -m pytest` invocation.

→ [02-evidence-and-claims.md](02-evidence-and-claims.md) maps claims to artifacts.
→ [04-negative-results-detail.md](04-negative-results-detail.md) lists results that
  do not replicate cleanly and why.

---

## Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Include the exact Python version in any summary artifact:

```bash
git rev-parse HEAD
python --version
```

---

## Core verification (all tests)

```bash
pytest -q
```

Expected: all tests pass. Any failure is a regression, do not proceed to
benchmarks until it is resolved.

---

## Claim 1, 0% unsafe execution on 700-task adversarial benchmark

```bash
python experiments/generate_toolcall_benchmark_v2.py
python experiments/evaluate_toolcall_benchmark_v2.py
python experiments/toolcall_ablation_v2.py
python experiments/toolcall_v2_significance.py
```

Expected output files:
- `artifacts/toolcall_benchmark_v2.json`
- `results/toolcall_benchmark_v2_summary.md`
- `results/toolcall_benchmark_v2_significance.json`

Committed metrics (`remora_full_policy_gate`): unsafe_execution_rate = 0.0000,
mean_utility = 0.6200, accuracy = 0.9000.

Caveat: deterministic simulator only, no real shell, network, database, git, or
file mutations are executed. See `docs/benchmarks/README.md`.

---

## Claim 2, 88% selective accuracy on held-out split

```bash
make holdout   # python scripts/selective_n500_holdout.py
```

Expected output files:
- `results/selective_n500_holdout_results.json`

Committed metrics (SAP v2 clean round, re-issued 2026-07-27): 100.0% selective
accuracy at 16.7% coverage, N_accepted = 18, Wilson CI [82.4%, 100.0%], exact
one-sided binomial vs the training-split null p0 = 84.86% giving p = 0.052.

Caveat: N_accepted = 18 and p = 0.052, so the result is directional, not
significant. **CLAIM-004 is superseded by CLAIM-012**: the temperature signal it
ranks on failed its fresh-data confirmation, so reproducing this number confirms
the artifact, not the hypothesis. Quote the CI, not the point estimate.

---

## Claim 3: Critical-phase trust inversion

```bash
python experiments/end_to_end_n500_v3.py   # in-sample full-dataset eval
```

The critical-phase trust-inversion split (low-trust critical items 76.2% correct,
N=21, vs high-trust 36.4%, N=11) is a documented negative result; see
`NEGATIVE_RESULTS.md` and `paper/remora_paper.md`. The per-item split is committed as
`results/critical_trust_split_v1.json` (reproduce with
`python scripts/compute_critical_trust_split.py`), computed at the τ=0.10
groupthink boundary from the N500 thermodynamic artifact; its buckets sum to
the committed aggregate of 20/32 correct. Small sample (N=32); a directional finding.

Unit tests: `remora/selective/guardrail.py`, 8 unit tests covering phase-aware
guardrail routing.

Caveat: small sample (N=32 critical items total).

---

## Claim 4: Tamper-evident audit chain

```bash
make shadow-replay INPUT=artifacts/demo/shadow_mode_sample_agent_action_log.jsonl
```

Expected output: reconstructed chain in `artifacts/shadow_mode/` with chain
integrity verified. Any modification to an envelope breaks the SHA-256 chain.

Implementation: `remora/audit/hash_chain.py`.

---

## Claim 5: Ordered-phase conformal coverage

```bash
python experiments/mondrian_repeated_splits.py
```

Expected: repeated-splits Mondrian conformal coverage per phase. The committed
99.9% / 0-of-20 ordered-phase figure at the 15% risk target is in
`results/mondrian_v2_repeated_splits.json` (v2, 2161 items); the script above
reproduces the repeated-splits methodology (see `paper/remora_paper.md` §9.3).

---

## Credibility pack (all headline results)

```bash
# 1) Core tests
pytest -q

# 2) Heavy replay segment
pytest -q -m live_replay_heavy \
  tests/test_toolcall_live_exec_results.py \
  tests/test_toolcall_live_cache_replay.py

# 3) Benchmark + holdout
make benchmark
make holdout

# 4) Governance benchmark package
make benchmark-package

# 5) Claim and consistency checks
python scripts/check_claim_consistency.py
python scripts/check_no_overclaims.py
python scripts/check_claim_sync.py
```

---

## Audit schema for external validation runs

Result JSONL schema (one object per line), required fields:

| Field | Type | Description |
|---|---|---|
| `dataset` | string | Dataset name |
| `item_id` | string | Unique item identifier |
| `question` | string | Input question or action |
| `expected_answer` | nullable | Ground truth if available |
| `oracle_raw_outputs` | list of string | Raw oracle responses |
| `oracle_normalized_outputs` | list of string | Normalised answers |
| `majority_answer` | nullable | Majority-vote answer |
| `remora_answer` | nullable | REMORA final answer |
| `action` | string | `accept`/`verify`/`abstain`/`escalate` |
| `phase` | string | `ordered`/`critical`/`disordered` |
| `trust` | number | Trust score |
| `H` | number | Entropy |
| `D` | number | Dissensus |
| `policy_reason` | string | Policy decision reason |
| `correct` | boolean or null | Correctness label |
| `unsafe_execution` | boolean | Whether an unsafe execution occurred |
| `decision_hash` | string | SHA-256 of the envelope |
| `timestamp` | string | ISO8601 |
| `model_providers` | list of {provider, model} | Oracle providers used |
| `prompt_template_version` | string | Template version |

Storage: `results/external_validation_raw.jsonl`, checksummed with SHA-256.
Add the hash to the summary artifact. Always record `git rev-parse HEAD` and
`python --version`.

---

## Limitations

- Tool-call safety figures are benchmark/simulator scoped, not deployment guarantees.
- Evidence verification pathways include proxy and retrieval-backed modes; external
  semantic validation remains an active workstream.
- Read `NEGATIVE_RESULTS.md` (→ [04-negative-results-detail.md](04-negative-results-detail.md)) before citing any number.
