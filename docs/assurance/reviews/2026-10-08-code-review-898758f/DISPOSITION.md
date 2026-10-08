# Code review of 898758f: disposition

> Review text and four regression tests supplied by the maintainer on
> 2026-10-08, reviewing `898758f7`; its author is not stated here. The review
> covered the effect domain, authentication and idempotency, evidence coverage
> and evidence admission, and says it is not an exhaustive audit. This
> disposition is producer-owned and AI-assisted (Claude Code). Every finding
> was reproduced against `898758f7` with the supplied tests before any change.
> Independence: NOT_ESTABLISHED.

All four findings were correct. Each one is fixed here, and each supplied test
passes after the fix. The repository's own regression tests are new; each one
fails on `898758f7` unless the table says otherwise.

| | Finding (review rank) | Disposition |
|---|---|---|
| CR898-1 | P1. A close does not stop a second effect worker | **FIXED** |
| CR898-2 | P1. An expired effect authority reopens on the next request | **FIXED** |
| CR898-3 | P2. Concurrent idempotent assessments mint two grants | **FIXED** |
| CR898-4 | P2. A cached answer skips the assess permission check | **FIXED** |

## CR898-1 and CR898-2: one deadline and one closure per execution

`remora/enforcement/effect_domain.py` checked the durable `effects-closed`
marker only when a worker opened an execution. A worker that already held the
execution in its process cache kept serving it after another worker's
`close()`. Separately, `_evict()` remembered an expired execution only until
its own expiry, so the next request under the same lease (120 s) derived a
fresh 60 s effect authority.

The session deadline is now fixed once. With a ledger, the first opener
records it as `effects-deadline:<digest>:<t>` on a 5-second grid, rounded
down, so the recorded deadline is never later than the derived one. Every
later opener, on any worker or after a restart, finds that key and derives its
authority for the time that remains; at or past the deadline the execution is
refused. The ledger stores keys only, so the reader probes the grid between
the lease's issue time and its expiry plus 60 s. Closure is checked after each
effect slot is claimed: a `close()` that completed before the claim stops the
effect, and an effect whose slot was claimed before the close completed may
finish. Without a ledger the same rules hold inside one process, where a
closed or expired execution stays closed until its lease can no longer open
one.

Recording the deadline is now the first ledger write of an execution. A ledger
that fails on that write refuses the execution before any effect, where it
used to fail one write later.

Tests: `tests/capabilities/test_effect_domain.py`, class
`TestCloseAndExpiryAcrossWorkers` and
`test_without_a_ledger_expiry_is_terminal_until_the_lease_ends`. Five of the
six fail on `898758f7`. The sixth,
`test_the_recorded_deadline_is_never_later_than_the_derived_one`, pins the
bound on the rounded deadline; `898758f7` meets it trivially with an exact
60 s authority.

## CR898-3: the key is reserved before anything is assessed

`servers/execution_api.py` read the idempotency cache, assessed, minted a
grant, and then wrote the cache with `INSERT OR IGNORE`. Two concurrent
requests could both miss, so both returned a signed grant that
`execute-accepted` would run.

`IdempotencyStore.claim` (`remora/persistence/idempotency.py`) now inserts a
pending reservation atomically before the assessment. The winner assesses and
calls `complete`. A concurrent request with the same key polls for up to 10 s
and returns the stored answer, or a 409 `idempotency_key in_progress` when the
owner has not finished. A failed assessment releases the key. The reservation
carries a SHA-256 fingerprint of the request without the key, and the same key
with a different request is a 409 `idempotency_key request_mismatch`. A
reservation whose owner crashed is taken over after 300 s. That window must
exceed any request's running time. An owner still running after it could
return its grant alongside the new owner's. Its late `complete` is refused, so
only the new owner's answer is stored. The SQLite and Postgres adapters
implement the reservation with conditional insert, update and delete on the
existing table; no schema change.

## CR898-4: the permission check comes first, and the key names the principal

The cached answer was returned before `_require_tenant_capability(...,
"assess")`, and the key was the tenant plus the caller's string. A viewer in
the same tenant who sent an operator's key received the operator's answer,
execution token included. The route now checks the permission and the request
before any stored answer, and the stored key includes a hash of the
authenticated principal, so one principal's key never answers another's
request.

The research surface `/v1/assess` (`servers/api.py`) already checked the
permission first. It had the same tenant-only key and the same race, and now
uses the same reservation with the principal in the key. Its route body moved
into `_assess_decide` unchanged, so the reservation can be released on every
exit.

Tests: `tests/test_assess_idempotency_reservation.py` (20). Four API tests
fail on `898758f7`: one grant under a forced concurrent miss, 403 for a viewer
replaying an operator's key, separate answers per principal, and a 409 for a
changed request. The rest cover replay, release after a failed assessment, and
the reservation on the in-memory and SQLite stores. The Postgres adapter was
not run here.

## Not changed

Existing idempotency rows written by `put` are not migrated. They sit under
the old tenant-only keys, which the routes no longer read, so a deployment
loses its stored answers once at upgrade and a retry across the upgrade is
assessed again.
