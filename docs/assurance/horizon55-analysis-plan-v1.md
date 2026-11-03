# Horizon #55 retrospective analysis plan v1

Status: retrospective plan for an exploratory, author-operated row. It is not
a preregistration. Package: [`integrations/horizon55/`](../../integrations/horizon55/README.md),
outputs in [`artifacts/interop/horizon55/`](../../artifacts/interop/horizon55/REPORT.md).

## Prior exposure

The Horizon Shield #51 set-2 records, including the A, B and C occurrences
and C's `budget_exceeded` outcome in the producer's settlement, were public
before this plan was written. The author read them while designing the claims.
Nothing in this row is blind, and freezing this document now cannot make it
so. The embargoed OSF registration `pxzj7` (HTTP 410 from the public OSF API on 2026-11-03, status unverified) covers a different
snapshot and is not a preregistration of this row.

## Questions

For each case, ten claims, each with one rule:

| Rule | Claim | Evidence it may use |
|---|---|---|
| H55-R01 | `native_delegation_scope` | holder use, responder receipt, root-issuer credential |
| H55-R02 | `budget_compliance` | issuer budget policy and authenticated payments, summed in log order |
| H55-R03 | `same_request_occurrence` | request digest named by use, payment, receipt and criteria |
| H55-R04 | `payment_execution_link` | payment logged before the receipt, same caller and responder |
| H55-R05 | `audit_byte_identity` | public audit bytes against the signed `response_sha256` |
| H55-R06 | `dataset_byte_identity` | dataset bytes against the audit's digest and the pin |
| H55-R07 | `dataset_runtime_use` | none available |
| H55-R08 | `receiver_accepted_result` | none public |
| H55-R09 | `remora_dispatch_authority` | none: no REMORA grant, lease or dispatch exists |
| H55-R10 | `physical_effect` | none: signed statements are not observations |

Delegation scope and budget are separate claims and are never combined. The
budget is a retrospective count, not a pre-dispatch decision.

## Frozen expectations

`EXPECTED` in `integrations/horizon55/run.py` holds the verdict table of SDD
section 2.2, written before the row first ran. `run.py --check` fails on any
verdict that differs from it. An expected `NOT_ESTABLISHED` counts as
agreement, not as a failure.

## Inputs

Horizon Shield revision `b85029de8d22c5246886f4f50ede03da0f54dfcf` and
dataset revision `5b22c203248b0149cd0456f77d32feb887f48ee0`, pinned file by
file in `inputs.lock.json`. The five digests in the SDD's input table matched
the fetched bytes exactly. Keys and trust configuration come from the
producer's bundle.

## Controls

Tests H55-T00 to T17 are in `tests/test_horizon55_inputs.py`,
`tests/test_horizon55_claims.py` and `tests/test_horizon55_mutations.py`.
The mutations are the author's own controls. They are not external
adversarial coverage and are not counted as such.

P1 controls, added 2026-10-24 after the row was published, are of the same
kind:

- `tests/test_horizon55_log_adversarial.py` covers the signed records:
  - a genuine payment entry replayed at the end or duplicated in place;
  - reordered entries, including B moved after C, which would otherwise put C
    within the budget;
  - a log truncated before C;
  - a tampered checkpoint;
  - a replayed entry whose position fields were rewritten;
  - a bundle copy of the log that disagrees with the files.

  None of them verifies, and none establishes a claim.
- `tests/test_horizon55_enforcement_adversarial.py` runs part 2 under
  concurrency, repeated execution, duplicate proposals, tool failures before
  and after the payment, restarts and every order.

  With the dispatcher's reservation disabled, 11 of its 12 tests fail. The
  twelfth checks that a grant is spent once.

## Deviations and findings during implementation

The mutation tests were written after the baseline verdicts were known. Two
of them found defects in the first version of `claims.py`, both fixed before
any output was published:

1. With an unverified log (a changed operator key, a swapped receipt or a
   mutated signed field), `audit_byte_identity` and `dataset_byte_identity`
   still returned `ESTABLISHED` for A and C. They now return
   `NOT_ESTABLISHED` with `log_not_verified`.
2. Evidence references were indexed by each entry's own `seq` field, so a
   removed entry crashed the row, and the budget policy reference leaked into
   the references of later claims. References now use the file position.

Neither fix changed a verdict or reason code on the unmodified inputs.

## Part 2, added by owner decision

The first version of this row read the records only and recorded that REMORA
could not have refused C. Replayed through REMORA's execution API, REMORA as
shipped ran all three payments (NEGATIVE_RESULTS.md section 97). The owner then
decided that REMORA must handle this, because the same pattern governs
setpoints and ventilation in the planned pilot. Cumulative limits were added to
REMORA's enforcement path in pull requests #1025, #1033 and #1037, outside
this package and not under this plan. `enforce.py` adds part 2: the verified
payments and the signed budget replayed through REMORA's own decision path,
with and without the limit. Its expected outcomes are pinned in `run.py`
(`EXPECTED_ENFORCEMENT`). They were written after the mechanism was built and
tested on the same sequence, so part 2 shows the mechanism works on the case it
was built for. It is not a measurement of how often it refuses legitimate
calls.

## Evidence extension: B's audit bytes (2026-10-24)

After the row was published, Horizon Shield published B's audit bytes at
`c824cbe61a383e57f1d9d15fea962a79f5b6bbd5` (1101 bytes, SHA-256
`40bc2a46f428b2cc5000e9d5e896adac218ebe3c2b76f78ba29afebf97887aea`, the
`response_sha256` B's execution receipt signs). The commit descends from the
frozen revision and changes no file the row reads. The frozen lock, `EXPECTED`
and `results.json` stay as they were: they are the record of what the frozen
inputs carry. The bytes enter through a second lock,
`audit-b/inputs.lock.json`, and a second run, `audit-b/results.json`, checked
against `EXPECTED_AUDIT_B`. That table is the frozen one with B's
`audit_byte_identity` and `dataset_byte_identity` set to `ESTABLISHED`. It was
written after the bytes were published and their digest compared with the
receipt, before the row ran on them, so it records a prediction from a known
digest, not a blind one. No other verdict may move. B's audit names a fixture
(`1f75bcab…`) that is not public, so the estimate B audited is not checked.

## Anchoring, checked separately (P2, 2026-10-24)

`anchor.py` checks the checkpoint's OpenTimestamps proof against Bitcoin
headers pinned from two explorers with different operators. It uses its own
parser and does not use the producer's proof summary or header view.
`EXPECTED_ANCHORING` (`ESTABLISHED`) was written after the proof was parsed
and before the headers were fetched. The frozen `results.json` keeps
`NOT_ESTABLISHED`.

The trust basis is two explorers agreeing at fetch time, plus proof of work
checked offline. It is not a node of ours. The single-byte mutation test over
the whole proof shows that no flipped byte yields a verified attestation with
a commitment other than the two genuine ones.

## Out of scope

No live calls, payments, cloud tokens or network access during `run.py` or
`enforce.py`. The frozen row does not verify the Bitcoin anchor. It is checked
separately (see below). No comparison of REMORA with
MUSUBI as more or less secure: they act at different points, before the call
and after it. A future study of
pre-dispatch budget enforcement would need a new synthetic population, an
unseen holdout and a prospective OSF registration before any data is read.
