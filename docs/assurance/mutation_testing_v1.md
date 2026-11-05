# Mutation testing v1 — the grant/lease/PEP consumption paths

- Status: first measured pass (issue #280); scoped, reproducible, with the
  numbers stated for what they are.
- Scope: `remora/enforcement/token.py`, `gate.py`, `lease.py`,
  `nonce_store.py`, the files carrying one-time consumption and exact-call
  binding, and since 2026-10-24 `cumulative_limits.py`, the budget the OT
  pilot's writes are reserved against (first measured 2026-11-04).
- Tooling: `mutmut` 3.8.0 (pinned; mutant ids are stable only within one
  version), configured in `pyproject.toml` `[tool.mutmut]`. The runner began as
  thirteen remora-only enforcement suites (~10 s) and is now the selection
  listed there (about 60 s, 2026-11-04). Runs on Linux/WSL (`mutmut run`);
  mutmut has no native Windows support.

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

## The 2026-10-13 re-measurement

The weekly sweep ran again after #826 repaired its sandbox, and failed with 528
survivors absent from the baseline. As in September, the count was mostly new
code: `dispatch` had been split into refusal hooks (`_effect_refusal`,
`_plan_refusal`, `_procedure_refusal`, `_surface_refusal`), and
`verify_authenticity` and `_signature_refusal` had no baseline entries at all.
It was not an accepted regression either. Each survivor was classified by
where its mutation sits (inside a `governance_event` call, inside a result
construction, or in logic), and every one was then killed or argued.

| Step | Mutants | Killed | Survived |
|---|---:|---:|---:|
| Weekly sweep, 2026-10-12 (runner) | 3,115 | 2,411 | 704 |
| Local re-run before any change | 3,115 | 2,446 | 634 |
| Three new contract modules (round 1) | 3,332 | 3,165 | 141 |
| Newly covered lines killed (round 2) | 3,337 | 3,218 | 110 |
| Fourth and fifth sweeps (round 3) | 3,358 | 3,245 | 104 |
| Peek test tightened after the fifth sweep (applied by hand) | 3,358 | 3,248 | 101 |

The pool grows each round because `mutate_only_covered_lines` mutates lines
the new tests reach for the first time: round 1 covered `_prepare_mediation`
and `_capability_refusal`, which then contributed 42 new survivors of their
own. Each round's verification applied every claimed kill to the source by
hand and ran only the affected module.

The tests are `tests/test_dispatch_refusal_contract.py`,
`tests/test_lease_refusal_hooks_contract.py` and
`tests/test_gate_token_nonce_mutation_contract.py`. They pin each refusal as
a whole result (`executed is False`, the exact reason, the identity fields and
`dispatch_check`) and each governance event by name, level and payload.

Writing them found two defects in the source, both fixed:

- `reset_ledger_watermark` had no D1 branch, so a Cloudflare deployment could
  see a ledger that had lost rows and could not re-baseline it after an
  authorized prune;
- the non-strict "unsigned token accepted" warning pointed at `check()` inside
  `gate.py` instead of its caller.

They also pinned behaviour that was right and unguarded. A context presented
for a lease bound to none must refuse. A caller mutating its own nested
arguments mid-dispatch must not change what runs. A peek at the SQLite ledger
must not spend a grant. A peek at a spent grant must report it spent.

The baseline now records 114 survivors (see the note on the first runner
sweep below for why not 101). Every one has a written argument in
`tests/data/mutation_equivalent_{dispatch,lease,gate_token_nonce}.txt`:

| Reason | Count |
|---|---:|
| Postgres-only branches, including their SQL text; the sweep runs without `REMORA_PG_DSN` | 45 |
| Unreachable defaults and arguments that cannot change behaviour | 38 |
| `"Z"` replacement before `fromisoformat`, a no-op on Python 3.11 and later | 13 |
| SQL keyword or name case on SQLite and D1, which ignore it | 14 |
| Killed by a test the sweep deselects (warning `stacklevel` under the trampoline) | 4 |
| **Total** | **114** |

A correction, recorded rather than erased: #839 merged three entries
(`_check_unlogged` 231, 232 and 234, fields of the D1 already-consumed result)
as open, "killed when applied by hand, survived in the sandbox". Both halves
were wrong. The hand application had used the second sweep's mutant bodies
under the third sweep's numbers, because a path edit to the apply script never
took effect. With the right bodies, the tightened peek test kills all three;
the fifth sweep had simply run before that test was tightened. They are
removed from the baseline. Every other hand verification of rounds 3 and 4 was
repeated with the right bodies and holds.

The first runner sweep after the merge (2026-10-13, master `553c5d91`,
3,581 mutants with token v3 included) failed on 13 survivors absent from the
baseline. None was new: all 13 already had a written argument (ten in
`EnforcementGate._ensure_table`, two in `DurableNonceStore._ensure_table`, one
`"Z"` replacement in `check_bindings`). The local sandbox had recorded them as
segfault or timeout rather than survived, and `--update` writes survivors
only, so the baseline left them out while the reasons file kept them. They are
added, which gives 114. `tests/test_mutation_baseline.py` now requires the
baseline and the argued set to be the same set in both directions, so a flaky
sandbox status cannot reopen the gap.

### Resolving the argued survivors (2026-10-13, evening)

Argued is not resolved. Of the 114 baseline entries, most were not equivalent
in the strict sense: they survived because no test could reach the code, or
because the code they changed did nothing.

- **Postgres was never executed.** The PEP consumed-grant ledger and the lease
  nonce store run on Postgres in production, and the sweep had no server.
  `tests/test_enforcement_ledgers_postgres.py` now runs both against one.
  It covers spend-once across gate instances, a peek that never spends, the
  watermark and a deleted row it reports. It also covers the reset, the
  named outage refusal, per-tenant nonces and replay. The scheduled
  sweep has a Postgres service and fails if that module skips; CI's
  `postgres-contract` job runs it on every push. Each test process works in
  its own schema, so the sweep's parallel workers cannot race.
- **Dead code.** `.replace("Z", "+00:00")` before `fromisoformat` does nothing
  on Python 3.11 and later; it is gone from token, lease and gate.
- **Unreachable defaults.** These were `getattr` on a dataclass field,
  registry generation defaults that `register()` always overwrites, and
  arguments equal to the dataclass default. So were a `_scalar` default
  around `COUNT(*)`, `getattr` for `commit` and `rollback` (all three
  backends implement both), a duplicate flag and a guard `partition` already
  covers. Each is now written as what it is.
- **Triplicated SQL.** `EnforcementGate` held one copy of every ledger
  statement per backend. That is how the D1 reset branch went missing. One
  `_ledger()` helper and one schema now serve Postgres, SQLite and D1.

| Step (local sweep, Postgres service) | Mutants | Killed | Survived |
|---|---:|---:|---:|
| Postgres contract, dead code and defaults removed, ledger helper | 3,456 | 3,431 | 25 |
| `_scalar`, commit/rollback `getattr`, duplicate flag removed | 3,412 | 3,393 | 19 |
| One ledger schema, redundant key-list guard removed | 3,404 | 3,387 | 17 |

The baseline holds 38, not 17, and it is chosen by construction, not by
observation. Equivalent mutants flipped between killed and survived from
one sweep to the next, locally and on the runner alike. The SQL-case
variants of one statement survived in one run and were killed in the next,
with identical mutant bodies. Running one of them alone, six times, it
survived every time. Run eight at a time locally, the Docker VM OOM-killed
workers, so memory pressure is one source of the noise. What kills them on
the runner is not established, and is an open finding. A baseline built
from one run's survivors therefore failed the next run. It now lists every
case-only mutant inside SQL text (26) plus the 12 other equivalents, and any
one sweep sees a subset survive (17 to 25 so far). A killed entry is a
ratchet hint, never a failure. The runner sweep also surfaced `consume`'s
default on the private `_check_unlogged`, which its only caller always
passes; the defaults are gone.

| Why the 38 cannot be killed | Count |
|---|---:|
| SQL keyword or name case; SQLite, D1 and Postgres fold unquoted names | 26 |
| `stacklevel` of a warning, killed by tests the trampoline forces the sweep to deselect | 4 |
| `None` for `False` where the value is only tested for truth (`live`, `require_expiry`) | 3 |
| `state_reader` on a mediator whose derived authority has no state condition | 2 |
| A string default that no comparison can tell from `""` | 2 |
| `or` for `and` behind a verify() refusal that admits only both or neither | 1 |
| **Total** | **38** |

Two case-only mutants are not equivalent and are not in the list. They
write the Postgres placeholder as `%S`, which psycopg rejects, and the
Postgres contract kills both. A first version of this section also excluded
`consumed_count` with `AS N`, reasoning that D1 returns the row as a dict
keyed `N`. The confirming runner sweep saw it survive, and run alone it
survives the D1 test: `D1Connection.fetchone()` returns a tuple, so the
`isinstance(row, dict)` branch that reads the alias is unreachable. The
mutant is equivalent and listed. The dead branch and the alias nothing read
were removed on 2026-10-14. The statement's two case-only mutants keep their
ids, `consumed_count__mutmut_3` and `__mutmut_4`, under mutmut 3.8.0. A
scoped sweep checked them, and they stay in the list as keyword-case
mutants like every other.

Agent-written tests were part of this pass: three parallel agents and one
second-round agent, each in its own worktree, with every kill verified by
applying the mutant. The verification is what makes them evidence here, not
who wrote them (docs/AI_USE.md).

## The 2026-11-04 re-measurement: the sweep had stopped measuring, and the limits were never in it

The scheduled sweep of 2026-11-02 (master `68760dee`) failed in its stats
phase, before any mutant ran: `tests/test_invocation_evidence_export.py`
reads `integrations/invocation-evidence/fixtures/` at import, and the
sandbox did not copy it. No results artifact exists for that run. The
sweep before it that completed was the 2026-10-13 baseline sweep.

Repairing the sandbox exposed a second, older gap. `cumulative_limits.py`
joined `only_mutate` on 2026-10-24 (#1046), but none of its suites in
`tests/limits/` was in the runner, and `tests/test_mutation_sweep_selection.py`
scanned only the top level of `tests/`. Recursing found seventeen more
importers of the mutated modules in `tests/capabilities/`,
`tests/conformance/` and `tests/flow/` that the sweep had never run. The
numbers below are therefore the first measurement of the limits module,
and the first with those modules in the runner.

| Step | Mutants | Killed | Survived | Timeout |
|---|---:|---:|---:|---:|
| Sandbox and selection repaired, before any new test (Python 3.13, local Postgres 16) | 5,999 | 5,348 | 649 | 2 |
| Confirming sweep after the kill rounds below | 6,077 | 5,865 | 210 | 2 |
| Last round applied by hand to the 210 (each verified in the sandbox) | 6,077 | 5,888 | 186 | 2 |
| Final confirming sweep (same tests, fresh sandbox) | 6,077 | 5,888 | 184 | 5 |

Timeouts are detected mutants, not survivors; which mutants time out varies
between sweeps (`_text` with an empty name passing validation, `_plan` with
`a == -2`, and in the final sweep three in `verify_authenticity`). The final
sweep found one survivor the earlier rounds had not: `_check_unlogged` with
`action=None` in the Postgres duplicate-key result. The Postgres contract now
pins the action of that refusal, and the kill was verified in the sandbox by
hand after the sweep, which is why the baseline holds 184 and not 185. The
pool grew
again between the second and third rows because the new tests cover lines the
old runner did not reach, which `mutate_only_covered_lines` then mutates.

The pool went 3,581 to 5,999: `cumulative_limits.py` is 1,389 lines, and the
new runner covers lines of `lease.py` and `gate.py` that the old one never
executed. Of the 649, 323 sat in `cumulative_limits.py`, 281 in `lease.py`
(158 of them in `dispatch`, 68 in `_limit_settle`), 39 in `gate.py`, and the
six remaining were baseline entries. Every one was classified by reading its
diff, and then killed or argued.

### What the survivors said about the execution path

The clusters were not random. Each names a contract the suites had used
but not pinned:

- **The dispatcher's limit hooks.** The dispatcher emits a governance event
  when a reservation cannot be given back or settled, and when the plant moved
  further than reserved (`dispatch.limit_release_failed`,
  `dispatch.limit_settle_failed`, `dispatch.limit_charged_after_the_fact`,
  `dispatch.limit_target_not_reached`). Every one survived field deletion and
  renaming. The existing tests asserted the event name as a substring of the
  log text, and `"XXdispatch.limit_release_failedXX"` contains the name.
- **The dispatch clock.** `_limit_refusal`, `_limit_settle` and the `dispatch`
  call sites could pass `None` for `now` and nothing noticed, because no
  test placed a reservation and a later call inside one window by the
  dispatch clock. With `None` the ledger uses the wall clock, and a window
  measured against the wrong clock is the difference between refusing the
  fourth setpoint move in an hour and allowing it.
- **The lease's expiry.** `expires_at` could be dropped from the reservation:
  a reservation whose lease expired before the tool started would then hold
  the budget until a restart.
- **The gate inside the caller's transaction.** `_spend_enlisted`, the path
  atomic admission (WS1 M4) uses, had no contract of its own. Unpinned were its
  refusal when a gate cannot join a transaction, its event, every field of its
  result, and the Postgres placeholder. The Postgres branch had never executed
  under a test, so `"%s"` could become `"?"` and nothing failed.
- **After-the-fact accounting.** The movement the controller reports beyond
  the reservation (`_account`) could be measured to the target instead of the
  observed value, and the loop could stop at the first record without a
  controller report. The existing test for this path happened to exhaust the
  limit with or without the extra charge, so the charge itself was never the
  deciding factor.
- **The invocation form.** The capability, effect and procedure checks run a
  second time over the resolved invocation arguments (IFC-06). That pass could
  hand `None` to any of them for the tool, tenant, target or set, or skip the
  procedure check. Every test with `invocation_arguments` ran without those
  hooks bound.
- **Policy validation messages.** 110 mutants in `LimitPolicy.from_dict`,
  `Meter.from_dict` and the signed-envelope check changed or blanked the
  message an operator reads when a signed `limits.json` is refused at
  startup. The tests asserted the exception class only.

### Kill rounds

Each kill was verified by running the new test against the mutant in the
sandbox (`MUTANT_UNDER_TEST`), module by module, before the confirming
sweep. The tests are `tests/limits/test_limits_mutation_contract.py` (new),
and additions to `tests/limits/test_limits_unit.py`,
`tests/limits/test_limits_postgres.py`,
`tests/test_gate_token_nonce_mutation_contract.py`,
`tests/test_enforcement_ledgers_postgres.py`,
`tests/test_dispatch_refusal_contract.py`, `tests/test_execution_lease.py`
and `tests/capabilities/test_flow_recipients.py`. They pin:

- Each limit event by name, level and whole payload. The events are pinned at
  the hook and through `dispatch`, beside the independent recorder's intent
  and outcome entries.
- The dispatch clock in the reservation, the after-the-fact charge and the
  refusal event. A call inside the window is refused and one outside it is
  allowed.
- The lease expiry. A reservation is released when its own lease expires, is
  not released while its tool is running, and is never released while the
  lease lives.
- `_spend_enlisted` on SQLite and on Postgres. The full result per branch, the
  `not_enlistable` event, the savepoint that leaves the caller's transaction
  usable, and the rollback that takes the spend with it.
- After-the-fact accounting measured to where the plant ended. It continues
  past a record without a controller report, can exhaust the limit on its
  own, and handles resources and limit ids that contain spaces.
- The reviewer's resolution as the ledger records it. The principal is refused
  before the evidence source is asked, and the resolution time is kept to the
  second on Postgres.
- The pilot's committed `deploy/ot-pilot/limits.json` verifies under the key
  the compose file trusts, and is refused with its budget widened by one.
- The operation key is a frozen canonical JSON digest, checked with a
  non-ASCII payee. Two tenants' identical payments are two operations.
- Every policy-validation message, with the bounds inclusive at both ends.
- The invocation form is judged by the procedure, capability and effect
  checks, and is deep-copied like the wire form.

### The residue, and why it cannot be killed

The baseline holds 184 entries, every one with a written argument in
`tests/data/mutation_equivalent_{limits,dispatch,lease,gate_token_nonce}.txt`
(`tests/test_mutation_baseline.py` requires the two sets to be equal). The
case-only SQL mutants are enumerated over the whole pool by construction,
from the sandbox's mutant functions, not read off one run's survivors: as the
October note records, any single sweep kills some of them. A killed entry is
a ratchet hint, never a failure.

| Why the 184 cannot be killed | Count |
|---|---:|
| SQL keyword or identifier case; SQLite, D1 and Postgres fold unquoted names (listed by construction over the whole pool) | 92 |
| SQL type name case or spelling on SQLite, which gives any declared type an affinity | 7 |
| Defaults, placeholders, seeds and keys that no code path reads or compares (`_plan`, `readings`, `preview`, `counter_key`, `debit`, `_spend_enlisted` messages, `_limit_refusal` placeholder, and the like) | 50 |
| `zip(strict=...)` over two sequences built from one tuple | 10 |
| The same value spelled differently (`"\\x1F"` for `"\\x1f"`, `"UTF-8"`, `split(sep)[0]` for `split(sep, 1)[0]`, a key separator on a JSON array) | 14 |
| `None` for `False` where the value is only tested for truth | 9 |
| `stacklevel` of a warning, killed by tests the trampoline forces the sweep to deselect | 2 |
| **Total** | **184** |

Three entries deserve a reader's attention. They are reachable in principle
and argued, not proved, equivalent. `dispatch__mutmut_417` is `or` for `and`
in the task-unchecked condition, and rests on `verify()` refusing half a task
identity. `_plan__mutmut_154` is the defensive `-1` clause of the
partial-retry guard. `verify__mutmut_147` is the flow-binding guard behind
the signature check. Each argument names the test that pins its premise.

### What this says about the OT pilot and WS1

The question behind this pass was how a deployment keeps the most utility
without giving up security. The repository's own evidence answers it in two
parts, and the survivors above sit exactly where the two meet.

**Where the utility is decided.** In the OT pilot every write is gated three
times. Policy routes it to review, an approver distinct from the proposer
approves it, and the cumulative limits in `deploy/ot-pilot/limits.json` meter
it at dispatch. The committed run
(`artifacts/pilot-pack/runs/ot-battery-2026-10-25/`) passed 16 of 16 cases
with 6 side effects: five writes ran after approval, and three were refused at
assess for `limit_coverage_unknown`, `limit_observation_unavailable` and
`limit_exceeded`. Reads resolve to VERIFY and run. The limits are therefore
the only control that decides between two approved writes. A 0.3 bar move of
PIC-101 runs; the fourth one in an hour does not. Their utility cost is the
legitimate write they refuse, and the pilot has no measurement of that rate
yet. NEGATIVE_RESULTS §97 says so: the mechanism "does not measure how often
legitimate payments are refused, which needs new tasks and a holdout". For
the refusals the limits do make to be worth their cost, the budget has to be
exact. It must be charged once, measured against the plant, given back only
when the call provably did not run, and counted in the right window. Every
cluster of survivors above was a hole in a test of exactly that. The window
is the dispatch clock. The release is the lease expiry and the trusted
source. The measurement is where the plant ended, not the target. The record
is the events an operator reads. None of them was a defect in the code. Each
was a place where a defect would have gone unnoticed.

**Where the security is decided.** WS1 Study C (NEGATIVE_RESULTS §96) is the
closest measurement of this trade: five arms on 825 episodes. Every WS1 arm
refused all 121 attack goals. The arms differed only in how many of the 33
benign reads they completed (20, 20 and 32 of 33), and the whole gap was the
monitor's veto threshold (0.3 against 0.4). The preconditions did all the
blocking, and the monitor's measured effect was lost utility. The replay at
0.35 would have recovered 12 of the 13 lost reads with no attack goal
released. The AgentDojo replay (§100) shows the other edge. Value-provenance
flow control kept every injected goal out and completed 7 of 18 tasks,
against 6 for refusing everything. The tasks write content derived from
untrusted reads, and no bounded lookup can vouch for free text.

**Reading the two together.** Utility is recovered by making the
deterministic checks exact and complete, not by loosening them. Every read the
WS1 arms lost was lost to a learned veto on a call whose preconditions had
proved. Every write the OT pilot refuses is refused by a declared number. The
deterministic hard guards (one-time grants, bound leases, exact limits) are
what let the arms execute 32 of 33 benign reads while refusing 121 of 121
attack goals. The mutation residue is where those guards were under-tested.
The kill rounds above change no decision, and they make every decision the
limits take observable. The utility work that remains is measurement, not
relaxation:

1. A holdout of legitimate OT writes under the pilot's limits, to put a
   number on `limit_exceeded` refusals of writes an operator would have made
   (the §97 gap).
2. A monitor threshold chosen on enough data, or a monitor that cannot veto
   a call whose preconditions proved (the §96 gap).
3. A planner that never sees untrusted data, if the AgentDojo-style tasks
   matter (the §100 gap).

None of these is a reason to weaken a hard guard. This document makes no
claim that the pilot's utility has been measured.

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
  enforcement behaviour (down from 159/53 before #405). Closed 2026-11-04:
  every remaining survivor in both functions is argued in
  `tests/data/mutation_equivalent_*.txt`.
- Generate this document's tables from the mutation-results artifact so the
  headline and per-function numbers cannot drift apart again (external
  review 2026-08-26 caught exactly that drift here).
- Coverage gap to the 95% targets for `remora/enforcement` (84.9) and
  `remora/execution` (93.7); floors are pinned at measured levels.
- The scheduled sweep has no guard that its stats phase collected: a sandbox
  that cannot import a selected module fails before any mutant runs, and the
  2026-11-02 failure sat unread for two days. A step that fails the job on a
  collection error, with the module named, is the cheap fix.
- The utility cost of the OT pilot's limits is unmeasured (the §97 gap); the
  mutation work makes the limits observable but puts no number on the
  legitimate writes they refuse.
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

### Specification mutation (2026-09-30)

Both sets above mutate `checker.py`. `scripts/spec_mutation_evidence_sufficiency.py` mutates the rules in `model.json` instead and runs each mutant model as a checker.
Equivalence is computed, not argued: the script enumerates eight premise value classes, three for premises no edit touches.
The catalogue and the pass criterion were pre-registered in section 13 of the v1.3 spec and pushed before the first score.

| Set | Mutants | Equivalent | Live | Row 1 | Row 3 |
|---|---:|---:|---:|---:|---:|
| first order | 446 | 54 | 392 | 380 | 392 |
| second order | 300 | 2 | 298 | 298 | 298 |

The twelve row-1 survivors are named in `docs/assurance/spec_mutation_baseline_evidence_sufficiency_v1.txt`.
They are open gaps, not equivalence labels (NEGATIVE_RESULTS.md §68). The gate fails on a new survivor on either row, and on a catalogue whose digest differs from the baseline header.

Evidence-sufficiency v1.4 adds the cases a rule-coverage criterion derives from `model.json` (v1.3 spec, section 14).
On v1.4 the same catalogue leaves no survivor on either row, and the gate now scores v1.4 against an empty baseline.
A held-out catalogue, pushed before v1.4 existed, adds two guard-placement operators and 300 third-order mutants.

| Catalogue | Corpus | Live | Row 1 | Row 3 |
|---|---|---:|---:|---:|
| first, first order | v1.3 | 392 | 380 | 392 |
| first, first order | v1.4 | 392 | 392 | 392 |
| held-out, first order | v1.3 | 19 | 18 | 19 |
| held-out, first order | v1.4 | 19 | 19 | 19 |
| held-out, third order | v1.3 | 300 | 300 | 300 |
| held-out, third order | v1.4 | 300 | 300 | 300 |

The held-out rows show how little that catalogue could tell the two corpora apart (NEGATIVE_RESULTS.md §69).
The two code-level gates above still score v1.3; v1.4 runs every v1.3 check on a superset of its cases.

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
