# Formal models

Machine-checked models for the formal mathematical assurance track
([SDD](../docs/design/formal-mathematical-assurance-v1.md), roadmap RF-16).
A model here is a statement about an abstraction. It is not a proof about the
Python or TypeScript code; correspondence is tested separately, and a result
is never stronger than that test.

## `tla/LeaseRetry.tla`

One logical operation in federation-port/v0's runtime as it was at `92d5078`:
admission, dispatch under a lease, retries, the admission deadline, and an
idempotent provider. Switches select the runtime's rule and the environment
(clock skew, crashes, provider outages). TLC explores every reachable state
of each configuration in [`tla/expected.json`](tla/expected.json):

| Configuration | Result |
|---|---|
| `pinned_reachable` | holds: the pinned rule is safe while every attempt can reach the provider |
| `pinned_outage` | violated: a lost response, an outage, the deadline. The operation closes as failed while the refund exists (CP-F4) |
| `pinned_skew_reachable` | holds: clock skew alone is not enough |
| `confirmfinal_all` | violated: making a confirmation final does not fix it |
| `sticky_all` | holds: "uncertainty sticky" under outages, crashes and skew |
| `sticky_confirmfinal_all` | holds |
| `sticky_confirmfinal_dispatch_after_expiry` | violated: past the deadline a retry is still dispatched (`NoDispatchAfterExpiry`) |
| `read_only_after_expiry` | holds: nothing is dispatched after the deadline, and all four invariants hold under outages, crashes and skew |

The merged runtime (`3a2f6ce`) corresponds to `read_only_after_expiry`: confirmation
final, uncertainty sticky and no dispatch after the deadline. The last two
configurations come from review of aeoess/federation-port#1: the
maintainer asked that an expired authorization never lead to a dispatch, with
read-only reconciliation afterwards. The model checks that rule as the invariant
`NoDispatchAfterExpiry`.

The model was written counterexample first. It had to reproduce the known
fault CP-F1 (found by a contract probe), and in doing so it found CP-F4, which
needs no skew and no crash. Contract probe CP-F4 then reproduced the model's
trace on the unmodified runtime, step for step. The probe is the evidence about
the code; the model is the reason to look.

## Run

```console
$ python scripts/check_tla_models.py
```

It needs Java 11+, downloads the pinned `tla2tools.jar` (v1.8.0, SHA-256 in
`expected.json`) into `.cache/tla/`, and compares each configuration's
verdict and counterexample trace with `expected.json`. Without Java or the
jar it prints `BLOCKED` and exits 2; an unchecked model is never reported as
passing. `tests/test_tla_models.py` runs it when Java is present and skips,
saying so, when it is not.

## Limits

The state space is finite (three attempts). "Holds" means no violation in
that space, not a proof for any number of attempts. The model abstracts
time to one deadline tick and the provider to one idempotent refund. No Lean
theorem exists yet; MODEL_PROVEN is not claimed for anything.
