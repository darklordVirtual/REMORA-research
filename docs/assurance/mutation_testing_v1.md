# Mutation testing v1 — the grant/lease/PEP consumption paths

- Status: first measured pass (issue #280); scoped, reproducible, with the
  numbers stated for what they are.
- Scope: `remora/enforcement/token.py`, `gate.py`, `lease.py`,
  `nonce_store.py`, the files carrying one-time consumption and exact-call
  binding.
- Tooling: `mutmut` 3.7, configured in `pyproject.toml` `[tool.mutmut]`;
  runner = the thirteen remora-only enforcement suites (~10 s). Runs on
  Linux/WSL (`mutmut run`); mutmut has no native Windows support.

## Why this metric, and what it cannot say

Mutation testing dates to DeMillo, Lipton and Sayward (1978), who proposed
seeding small faults into a program and asking whether the existing tests
notice. Two assumptions carry the method. Competent programmers write code that is
close to correct, so realistic faults are small edits. Simple faults couple to
complex ones, so a suite that catches the small edits tends to catch the larger
ones. Jia and Harman (2011) survey the four decades
between that paper and modern tooling, including the cost controls this
configuration relies on (a scoped mutant pool, a selected runner).

Two limits bound what the numbers in this document mean, and both are
load-bearing for how the gate is written:

- **Equivalent mutants are undecidable in general** (Budd and Angluin, 1982).
  A mutant that changes no observable behaviour can never be killed, so a
  100% kill rate is not the target and a surviving mutant is not by itself a
  defect. This is why the gate ratchets against a committed baseline of named
  survivors instead of enforcing a score. A number would force the equivalent
  mutants to be argued away. A named set can simply carry them.
- **The kill rate is a proxy for fault detection, not a measurement of it.**
  Just et al. (2014) found mutant detection correlated with real fault
  detection more strongly than coverage did. Papadakis et al. (2018) then
  showed that much of that correlation is explained by test-suite size, so the
  residual signal is weaker than the headline suggests. The honest reading of the tables above is comparative: this suite against
  itself over time, on one scoped set of modules. It is not a defect-density
  estimate, and no claim in the claim register derives a guarantee from it.

A third limit is specific to this setup rather than to the method, and it has
now produced two separate false readings: **the measurement describes the
runner, not the suite**. A kill test the runner never executes kills nothing
(round three above), and a test module missing from
`pytest_add_cli_args_test_selection` makes every mutant it would have killed
report as a survivor. `tests/test_mutation_sweep_selection.py` turns that
from a lesson into a gate.

References:

- R. A. DeMillo, R. J. Lipton, F. G. Sayward. "Hints on Test Data Selection:
  Help for the Practicing Programmer." *IEEE Computer* 11(4):34-41, 1978.
- T. A. Budd, D. Angluin. "Two notions of correctness and their relation to
  testing." *Acta Informatica* 18(1):31-45, 1982.
- Y. Jia, M. Harman. "An Analysis and Survey of the Development of Mutation
  Testing." *IEEE Transactions on Software Engineering* 37(5):649-678, 2011.
- R. Just, D. Jalali, L. Inozemtseva, M. D. Ernst, R. Holmes, G. Fraser. "Are
  mutants a valid substitute for real faults in software testing?" *FSE*,
  2014.
- M. Papadakis, D. Shin, S. Yoo, D.-H. Bae. "Are mutation scores correlated
  with real fault detection? A large scale empirical study on the
  relationship between mutants and real faults." *ICSE*, 2018.

## Measured results (2026-08-25)

| Run | Mutants | Killed | Survived | No tests | Kill rate |
|---|---|---|---|---|---|
| All lines | 1,138 | 382 | 704 | 52 | 35.2% of checked |
| Covered lines only (`mutate_only_covered_lines`) | 722 | 376 | 346 | 0 | 52.1% |
| Covered lines, after the golden-vector fix | 722 | 410 | 312 | 0 | 56.8% |
| Covered lines, after the gate-contract round | 778 | 484 | 294 | 0 | 62.2% |
| Covered lines, after the dispatcher-contract round | 811 | **518** | **293** | 0 | **63.9%** |
| Baseline sweep for the scheduled job (config committed) | 816 | 525 | **291** | 0 | 64.3% |
| After the governance-event contract round | 826 | **658** | **168** | 0 | **79.7%** |
| After the selection repair and the 2026-09-21 rounds | 1,909 | **1,615** | **294** | 0 | **84.6%** |

Round three (`tests/test_dispatcher_contract.py`) is the instructive one to
read carefully: the headline `dispatch` cluster went 157 → **159** while
the overall rate improved, because the contract tests execute
previously-unrun lines whose mutants are of a different *kind*. Sampled
diffs classify the residue: governance-event payload literals
(`"nonce_already_consumed"` → uppercase survives because no test asserts
log payloads), default-parameter values callers always override, and
exception-message content. One sampled survivor was a genuine gap, fixed
in the same round: **dropping `toolspec_hash` from the verify call
survived**: nothing dispatched with a *wrong* resolved spec identity,
only with a raising resolver. It now has its own kill test.

The open decision above was taken in the promoting direction (last row of
the table): governance events ARE contract.
`tests/test_governance_event_contract.py` pins the payloads via caplog on
`remora.governance`: the PEP decision event on allow and refusal, every
`dispatch.refused` reason literal with its lifecycle join keys,
`lease.issued`, `dispatch.executed`, `dispatch.state_unknown`, and the
emitter's secret-name screen in both directions. Writing the tests
surfaced a real defect, fixed in the same round: **`grant.checked` was
emitted only on the fall-through path of `EnforcementGate.check()`**;
every early refusal return (bad signature, audience, stale timestamps,
replay, unavailable ledger) left no operational record. `check()` now
funnels every exit of `_check_unlogged()` through the emitter. The round
killed 139 baseline survivors (`dispatch` 159 to 53, the check logic,
now `_check_unlogged`, 53 to 16) and moved the covered-lines rate
64.3% → 79.7%; the remaining 168 are default-parameter and
exception-message residue plus long-tail helpers (`try_consume` 15,
`verify_ledger` 14, `__init__`/parse helpers).

The fourth row is round two: `tests/test_enforcement_gate_contract.py`
pins the complete `(allowed, action, token_verified, reason, strict_mode)`
tuple per refusal branch of `check()`, with the age tests sitting exactly
on the boundary. The `check` cluster fell 53 → 36; the mutant pool grew
(722 → 778) because the new tests execute lines the old runner did not,
which is the correct direction: covered-lines mutation counts grow as
coverage grows, and the kill rate must be read against its own pool.

The third row is the verification that the fix below fixes: the
`_canonical_payload` cluster went 34 → 0 survivors, and the delta accounts
for the entire improvement. It took two attempts; the first re-sweep
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

## The 2026-09-21 re-measurement

The sweep had not executed since the project was renamed to
`remora-assurance`. Its install step uninstalled a distribution name that no
longer existed, so the installed package kept shadowing the mutated sources.
The guard described in caveat 1 then refused to run. The first sweep after
that fix reported 226 survivors absent from the baseline, which reads as a
collapse and is not one.

Read the pool, not the count. The mutant pool went 826 to 1,909: the four
modules acquired task binding, runtime trust identity, toolspec binding and
proposal binding in the intervening month, and `mutate_only_covered_lines`
grows the pool as coverage grows. The kill rate went 79.7% to 84.6% across the
same interval. 145 of the new survivors sat in 13 functions with no baseline
entry at all, which is new code, not regressed code.

Two repairs and two kill rounds, each re-measured on the runner:

| Step | New survivors vs the old baseline |
|---|---|
| Install defect fixed, sweep executes again | 226 |
| Test selection extended from 17 to 38 modules | 229 |
| Context/observation golden vectors + `check_bindings` contract | 194 |
| Lease verification completeness + signed-preimage invariants | 181 |

The selection repair is the instructive one because it did **not** help. The
frozen 17-file runner was missing 21 modules that import the mutated code.
Handing them to the mutants moved the count by +3. The hypothesis that the
survivors were a measurement artefact was wrong, and the measurement says so.
What did work was the technique this document already recorded. Freeze the
bytes (`AuthorizationContext.hash`, `_hash_observation`, the lease preimage).
Assert the exact refusal literal per branch, not the fact of refusal. 48 mutants died across the two rounds, and the clusters they came
from went to zero or near it.

The residue is the shape described above: governance-event payload literals,
default parameters callers always override, and exception-message content. The
baseline now records 294 named survivors rather than 168. That is a larger set
over a pool more than twice the size, not an accepted regression. The
per-function breakdown is in the baseline file itself.

## Survivors on covered lines, by function (pre-#405 baseline, 64.3 %)

Historical table kept for the delta analysis above; the current numbers
after the event-contract round are `dispatch` 53, `_check_unlogged` 16,
`_canonical_payload` 0 (see the 79.7 % summary at the top).

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
test (issue, then verify) is structurally blind to mutations applied to both
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
   reported 0 killed / 704 survived, a number that looked like a
   catastrophic test suite and was actually a broken experiment. The
   runner venv must carry dependencies only, never the package.
2. **Run from a native filesystem.** Over the WSL 9p mount the sweep did
   not finish a stats phase in ten minutes; from ext4 (`git archive` into
   `/tmp`) the full sweep runs at ~46–60 mutations/second and completes in
   under a minute.

## Open, tracked in #280

- Triage rounds for the remaining `dispatch` (53) and `_check_unlogged` (16)
  survivors, the two functions where surviving mutants sit closest to
  enforcement behaviour (down from 159/53 before #405).
- Generate this document's tables from the mutation-results artifact so the
  headline and per-function numbers cannot drift apart again (external
  review 2026-08-26 caught exactly that drift here).
- Coverage gap to the 95% targets for `remora/enforcement` (84.9) and
  `remora/execution` (93.7); floors are pinned at measured levels.
## Evidence-sufficiency checker sweep (2026-09-30)

A second subject, measured the same way and ratcheted the same way. The
subject is `conformance/evidence-sufficiency-v1/checker.py` (341 lines, sha256
`c4ca50ae…`, frozen since v1). The runner is the v1.3 corpus in the three
projections of the external runs. The tool is mutmut 3.8.0 with default
operators, in a sandbox that `scripts/mutation_evidence_sufficiency.py`
builds. The checker is imported by path rather than as a package, so it needs
its own sandbox and cannot use the `[tool.mutmut]` block above. The design
and the decisions are in `docs/design/evidence-sufficiency-v1.3.md`; the
finding is NEGATIVE_RESULTS.md §65.

| Run | Mutants | Killed | Survived | Survivors by family |
|---|---:|---:|---:|---|
| v1.2 corpus | 489 | 377 | 112 | A 41, B 40, C 12, D 8, E 3, F 7, G 1 |
| v1.3 corpus | 489 | 469 | 20 | C 12, F 7, G 1 |

The first row reproduces with `python scripts/mutation_evidence_sufficiency.py --scoring-suite evidence-sufficiency-v1.2`.
The second reproduces with the default command. mutmut refuses native Windows, so both were reproduced in a `python:3.12-slim` container; the raw `mutmut results --all` text of each is in `artifacts/evidence-sufficiency-mutation-2026-09-30/`.

Every survivor of the v1.3 run is named in
`docs/assurance/mutation_baseline_evidence_sufficiency_v1.txt`, and every one
is argued equivalent under the contract the corpus pins. The argument is per
family, so a reviewer can test the clause rather than the count:

| Family | Mutant ids | Why it is equivalent under the pinned contract |
|---|---|---|
| C, message text | `x_assess__mutmut_6` to `_10`, `_14` to `_16`; `x_validate_json__mutmut_15` to `_18` | D-7 pins the exception class for malformed input, not the message. A test that asserted the wording would pin prose, and the corpus refuses to |
| F, canonical string form | `x_canonical__mutmut_4`, `_5`, `_8`, `_9`, `_11`, `_12`, `_13` | `canonical()` is used for equality only. Separators and `ensure_ascii` change the text of the encoding and never the equality relation on JSON values; MR-11 pins the relation, not the text |
| G, `and` for `or` in `_result` | `x__result__mutmut_3` | reachable only when an inconclusive reason is missing from the guidance table or a decisive reason is present in it. R-5 (`undeclared_guidance`, `orphan_guidance`) fails on either, so the branch the mutant changes is dead under the corpus's own invariant |

The four families that were real gaps (A, B, D, E, 92 mutants) are killed by
the v1.3 additions. `tests/test_evidence_sufficiency_v1_3.py` keeps one
representative of each as a fault that v1.3 must fail and v1.2 must not.
The remaining caveat is the one at the top of this document: the sweep
measures the corpus against mutmut's operators, and a fault the tool never
generates is not measured.

### A second operator set (2026-09-30)

To measure the corpus against faults it was not tuned to,
`scripts/mutation_evidence_sufficiency_ast.py` applies nine operators mutmut
does not have and a fixed-seed sample of 200 second-order pairs. Every mutant
is a text edit on the checker's source, scored in process by the v1.3
runner. Each kill carries the set of checks that produced it (D-15 of the
v1.3 spec).

| Run | Mutants | Killed | Survived | Kills resting on one check | `--corpus` |
|---|---:|---:|---:|---|---|
| v1.3 before R18-R20 and the K1 cases | 905 | 898 | 7 | 57: reference model 42, rejection contract 14, crash 1 | `first-run` |
| v1.3 with R18-R20, before the K1 cases | 905 | 901 | 4 | 60: reference model 42, rejection contract 17, crash 1 | `without-k1` |
| v1.3 as merged | 905 | 901 | 4 | 18: rejection contract 17, crash 1 | `merged` (default) |

The first row first read "60: reference model 42, rejection contract 17", the figure of the second row (NEGATIVE_RESULTS.md §67).
The two middle states were never committed on their own; the script rebuilds each by removal, and the raw output of every row is in `artifacts/evidence-sufficiency-mutation-2026-09-30/`.

Per operator, as merged: delete_statement 86/86, swap_adjacent_guards 21/24,
comparison_variant 96/96, reason_confusion 236/236, status_polarity 16/16,
field_confusion 197/197, state_comparison 9/10, negate_condition 33/33,
type_vocabulary 7/7, second order 200/200. The 42 kills that rested on the
reference model alone were typed-premise faults on premises no authored case
had typed (NEGATIVE_RESULTS.md §66); they became the K1 cases. The three
`type_vocabulary` survivors of the first run were `isinstance` relaxations of
the exact type checks; rejections R18 to R20 kill them.

| Mutant id | Why it is equivalent under the pinned contract |
|---|---|
| `state_comparison:postcondition_observed:5` | `canonical()` output starts and ends with a JSON token, never whitespace, so `.strip()` on both sides is the identity on every value the vocabulary admits |
| `swap_adjacent_guards:assess:0` | the premise-source guard and the claim guard both raise `ValueError`; swapping them changes which message is raised when both fail, and D-7 pins the class, not the message |
| `swap_adjacent_guards:validate_json:0` | the scalar guard and the list guard are mutually exclusive on `type(value)`, so their order cannot change any outcome |
| `swap_adjacent_guards:validate_json:1` | the list guard and the mapping guard are mutually exclusive in the same way |

## CI integration (wired)

The scheduled job `.github/workflows/mutation.yml` (Mondays 05:00 UTC +
`workflow_dispatch`) runs the committed `[tool.mutmut]` configuration;
`mutate_only_covered_lines` is now permanent, so the job measures the
covered-lines metric this report argues for, and hands `mutmut results`
to `scripts/check_mutation_baseline.py`. The gate is asymmetric by design:

- a surviving mutant absent from `docs/assurance/mutation_baseline_v1.txt`
  FAILS the job (test-strength regression, named individually);
- a baseline entry that no longer survives is an advisory ratchet hint
  (progress never breaks the job), lowered only by regenerating the baseline
  in a reviewed diff (`mutmut results | python
  scripts/check_mutation_baseline.py --update -`);
- baseline entries whose whole function id-set vanished are classified as
  rename/removal maintenance, because mutant ids embed function names.

Baseline sweep (last row of the table): 816 mutants, 525 killed, 291
survivors recorded. The job installs dependencies only and asserts
`import remora` fails before sweeping: caveat 1 as an executable guard.
