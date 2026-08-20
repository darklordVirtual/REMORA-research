# ADR: Tainted arguments — approval suffices; sanitisation is not required

- Status: **accepted** (2026-08-20)
- Deciders: repository owner
- Closes: issue #40 (option **a**)
- Related: `remora/policy/decision_engine.py` (`argument_tainted` branch),
  `remora/governance/review_queue.py` (execution re-gate),
  `tests/test_tainted_argument_approval_contract.py`,
  `docs/13-research-frontier-roadmap.md` RF-02

## Context

`argument_tainted` marks a call whose arguments derive from untrusted content.
The 2026-07-27 architecture review asked whether a tainted CRITICAL production
write could reach human review and be approved without the argument ever being
sanitised or revalidated, and left three options open:

- **(a)** approval suffices as-is;
- **(b)** tainted arguments must be sanitised and revalidated before approval is
  grantable;
- **(c)** tainted critical writes always ABSTAIN or ESCALATE.

Option (c) shipped in #94 for the critical tier. What remained open was (b).

## Current behaviour, measured

The taint branch has three rungs, in order:

1. **Untrusted content controls a sensitive argument** — ESCALATE
   (`UNTRUSTED_CONTROLS_SENSITIVE_ARGUMENT`), independent of the declared risk
   tier. A caller-supplied "low" must not buy autonomy for an attacker-chosen
   recipient.
2. **Tainted at CRITICAL risk** — ESCALATE (`TAINTED_ARGUMENT_ESCALATE`).
3. **Tainted below CRITICAL** — VERIFY floor (`TAINTED_ARGUMENT_VERIFY`).

The execution re-gate (`ReviewQueue.execute`) redeems an approval against a
*fresh* decision and admits only ACCEPT or VERIFY. ESCALATE is not executable.

That yields the fact the original finding did not have: **for the scenario the
review actually named — a tainted CRITICAL write — approval already cannot be
redeemed.** The reviewer may approve the item; the re-gate refuses it while the
taint stands. No sanitisation machinery is required to stop that call, because
it never reaches dispatch.

## Decision

**Option (a): approval suffices as-is. Option (b) is not pursued.**

Rationale:

1. The case the review was worried about is already closed by rungs 1–2 plus the
   re-gate, and is closed *structurally* rather than by reviewer discipline.
2. Escalating every tainted call would send a summary of an untrusted email to a
   human for a decision there is nothing to decide. Friction with no decision
   value is how review queues stop being read, and §39 measured what a stricter
   semantic policy costs in autonomy: legitimate read autonomy fell to
   25/94 = 26.6% against a 75% target.
3. Option (b) requires a sanitiser REMORA cannot honestly own. With a single
   caller-asserted taint bit there is no per-value provenance to revalidate
   *against*; a "sanitised" flag would be one more assertion, not a check. The
   machinery that would make (b) meaningful is per-value labels with flow
   propagation, which is RF-02, not this issue.

## Residual risk, stated plainly

**Below CRITICAL, an approved tainted call executes with the taint standing.**
The argument is neither sanitised nor revalidated; the human approval is the
only thing between untrusted-derived arguments and dispatch. This is a
deliberate acceptance, not an oversight, and it is pinned by
`test_below_critical_an_approved_tainted_call_does_execute_unsanitised`.

Two further limits carry with it:

- **The taint bit is caller-asserted.** REMORA does not derive it and cannot
  check it. A caller that never sets `argument_tainted` gets none of the three
  rungs. This is the one-bit-taint limitation recorded in RF-02.
- **Clearing the flag is also caller-asserted.** A fresh observation with
  `argument_tainted=False` is taken at its word, so a caller may unblock its own
  call by declaring the argument clean.

## Consequences

- No behavioural change, so no policy version bump and no benchmark
  regeneration.
- The contract is now pinned by tests rather than by the decision-engine
  comment alone: all three rungs, the critical re-gate refusal, and the
  residual.
- If per-value taint labels ship under RF-02, this ADR is superseded rather than
  amended — the reason for (a) is the absence of anything to revalidate
  against, and RF-02 removes that reason.
- If the residual test ever starts failing because a below-critical tainted call
  is refused, option (b) has effectively shipped by accident and this ADR must
  be revisited rather than the test relaxed.
