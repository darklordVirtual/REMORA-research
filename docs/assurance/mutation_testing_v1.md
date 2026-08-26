# Mutation testing v1 — the grant/lease/PEP consumption paths

- Status: first measured pass (issue #280); scoped, reproducible, with the
  numbers stated for what they are.
- Scope: `remora/enforcement/token.py`, `gate.py`, `lease.py`,
  `nonce_store.py` — the files carrying one-time consumption and exact-call
  binding.
- Tooling: `mutmut` 3.7, configured in `pyproject.toml` `[tool.mutmut]`;
  runner = the thirteen remora-only enforcement suites (~10 s). Runs on
  Linux/WSL (`mutmut run`); mutmut has no native Windows support.

## Measured results (2026-08-25)

| Run | Mutants | Killed | Survived | No tests | Kill rate |
|---|---|---|---|---|---|
| All lines | 1,138 | 382 | 704 | 52 | 35.2% of checked |
| Covered lines only (`mutate_only_covered_lines`) | 722 | 376 | 346 | 0 | 52.1% |
| Covered lines, after the golden-vector fix | 722 | 410 | 312 | 0 | 56.8% |
| Covered lines, after the gate-contract round | 778 | 484 | 294 | 0 | 62.2% |
| Covered lines, after the dispatcher-contract round | 811 | **518** | **293** | 0 | **63.9%** |
| Baseline sweep for the scheduled job (config committed) | 816 | 525 | **291** | 0 | 64.3% |

Round three (`tests/test_dispatcher_contract.py`) is the instructive one to
read carefully: the headline `dispatch` cluster went 157 → **159** while
the overall rate improved, because the contract tests execute
previously-unrun lines whose mutants are of a different *kind*. Sampled
diffs classify the residue: governance-event payload literals
(`"nonce_already_consumed"` → uppercase survives because no test asserts
log payloads), default-parameter values callers always override, and
exception-message content. One sampled survivor was a genuine gap, fixed
in the same round: **dropping `toolspec_hash` from the verify call
survived** — nothing dispatched with a *wrong* resolved spec identity,
only with a raising resolver — and now has its own kill test. The honest
next rounds are observability-contract tests (asserting event payloads via
caplog) if event fidelity is promoted to a tested contract, or accepting
log-literal mutants as out of contract and recording that decision here.

The fourth row is round two: `tests/test_enforcement_gate_contract.py`
pins the complete `(allowed, action, token_verified, reason, strict_mode)`
tuple per refusal branch of `check()`, with the age tests sitting exactly
on the boundary. The `check` cluster fell 53 → 36; the mutant pool grew
(722 → 778) because the new tests execute lines the old runner did not,
which is the correct direction — covered-lines mutation counts grow as
coverage grows, and the kill rate must be read against its own pool.

The third row is the verification that the fix below fixes: the
`_canonical_payload` cluster went 34 → 0 survivors, and the delta accounts
for the entire improvement. It took two attempts — the first re-sweep
reproduced 34 unchanged because the new suite was not in the runner's test
selection, which is its own lesson: a kill-test that the runner never
executes kills nothing, however good it looks.

The two numbers answer different questions and neither may borrow the
other's meaning. The all-lines rate mixes untested *behaviour* with lines
the scoped runner never executes (the D1/Postgres adapter branches that the
coverage gate already documents as contract-tested elsewhere). The
covered-lines rate is the honest test-quality signal for this runner: on
lines these suites do execute, roughly half of small semantic changes go
unnoticed.

## Survivors on covered lines, by function

| Survivors | Function | Reading |
|---|---|---|
| 157 | `lease.GovernedToolDispatcher.dispatch` | the largest cluster; refusal-detail and event-payload branches asserted weakly — next triage round |
| 53 | `gate.EnforcementGate.check` | same shape; verification-order and result-field mutants |
| 34 | `token._canonical_payload` | **self-consistent mutants**: sign and verify share the mutated function, so renaming a payload key or altering serialization survives every roundtrip test. Killed by the golden signature vectors in `tests/test_token_golden_vectors.py` |
| 14+11 | `nonce_store.try_consume` / `_is_duplicate` | duplicate-classification message branches |
| 14+8 | `gate.verify_ledger` / `reset_ledger_watermark` | diagnostics paths, thin assertions |
| rest | init/parse helpers | long tail, low individual value |

## What was fixed as part of this pass

The `_canonical_payload` cluster is the instructive one: every roundtrip
test (issue → verify) is structurally blind to mutations applied to both
sides of the signature. `tests/test_token_golden_vectors.py` freezes the
canonical payload bytes and HMAC-SHA256 hex for a fixed key at two points
of the optional-field lattice (minimal and fully-populated), so any drift
in key names, ordering, separators, included-only-when-set discipline or
the MAC construction breaks a committed vector. This is also the class of
defect the paper's wire-format claims depend on.

## Two measurement caveats, learned the expensive way

1. **Editable installs make every mutant invisible.** With the package
   `pip install -e` into the runner venv, the sandbox's mutated sources
   lost import resolution to the original tree and the first sweep
   reported 0 killed / 704 survived — a number that looked like a
   catastrophic test suite and was actually a broken experiment. The
   runner venv must carry dependencies only, never the package.
2. **Run from a native filesystem.** Over the WSL 9p mount the sweep did
   not finish a stats phase in ten minutes; from ext4 (`git archive` into
   `/tmp`) the full sweep runs at ~46–60 mutations/second and completes in
   under a minute.

## Open, tracked in #280

- Triage rounds for the `dispatch` (157) and `check` (53) clusters — the
  two functions where surviving mutants sit closest to enforcement
  behaviour.
- Coverage gap to the 95% targets for `remora/enforcement` (84.9) and
  `remora/execution` (93.7); floors are pinned at measured levels.
## CI integration (wired)

The scheduled job `.github/workflows/mutation.yml` (Mondays 05:00 UTC +
`workflow_dispatch`) runs the committed `[tool.mutmut]` configuration —
`mutate_only_covered_lines` is now permanent, so the job measures the
covered-lines metric this report argues for — and hands `mutmut results`
to `scripts/check_mutation_baseline.py`. The gate is asymmetric by design:

- a surviving mutant absent from `docs/assurance/mutation_baseline_v1.txt`
  FAILS the job (test-strength regression, named individually);
- a baseline entry that no longer survives is an advisory ratchet hint —
  progress never breaks the job — lowered only by regenerating the baseline
  in a reviewed diff (`mutmut results | python
  scripts/check_mutation_baseline.py --update -`);
- baseline entries whose whole function id-set vanished are classified as
  rename/removal maintenance, because mutant ids embed function names.

Baseline sweep (last row of the table): 816 mutants, 525 killed, 291
survivors recorded. The job installs dependencies only and asserts
`import remora` fails before sweeping — caveat 1 as an executable guard.
