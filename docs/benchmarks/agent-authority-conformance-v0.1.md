# Agent Authority Conformance v0.1

**Status:** draft specification, vendor-neutral. Not a standard, not a
certification, not a ranking. Version v0.1 means the property definitions are
stable enough to apply to a second system, and nothing more.

**Purpose.** When an agent runtime says "the tool call was authorized", that
sentence hides at least seven separable questions. This document names them, so
that two systems built on different assumptions can state precisely what each
has demonstrated, what it has not demonstrated, and what it deliberately does
not try to solve. The output of an assessment is a per-property status with an
evidence reference. There is no aggregate score, and producing one is a
conformance error (§6).

**Non-goals.** This model does not measure agent capability, task success,
model safety, or product readiness. It says nothing about which system is
better. A narrow, well-evidenced claim is the desirable outcome, not a weak
one.

---

## 1. The seven properties

The properties are deliberately **separable**. Evidence for one grants no
credit in another. The most common conformance error is transitive credit, so
each definition below ends with the inference it forbids.

### A. Receipt Integrity

*Can the authorization artifact (receipt, grant, token, capability, lease) be
verified as authentic, unmodified and currently valid?*

In scope: signature or MAC verification, tamper detection over the full field
set, expiry, not-before, maximum age, single-use or replay semantics, binding
to an identity or proposal.

Does **not** imply: that the authority behind the artifact was legitimate (B),
that it names the call being made (C), or that anything happened (G).

### B. Authority Provenance

*Can the system prove who or what held the authority to authorize this action?*

In scope: actor identity and how it is established, policy authority, reviewer
or approver authority and role enforcement, delegation chains and attenuation,
tenant scope, provenance of the approved intent.

Does **not** imply: receipt integrity (A). An authentic artifact signed by an
unauthorized issuer, or approved by a principal without the role, satisfies A
and fails B.

### C. Exact-Call Integrity

*Is the authorization bound to the exact call that is executed?*

In scope: tool identity, full argument binding (not a summary or a subset),
target, tenant, proposal identity, call identity, an immutable binding such as
a canonical hash recomputed at dispatch, resistance to argument substitution
under a replayed or reused call identity.

Does **not** imply: that the exactly-bound call was the *right* call (D), or
that the binding held across a state change (F).

### D. Semantic Authority

*Was the action permitted in its real operational meaning?*

In scope: whether the intended subject, resource, tenant, time window and
target system were the correct ones; whether a valid business intent existed;
and, critically, **where the meaning came from**. An intent constructed by the
agent from its own reading of its own proposal is not deployment-owned
authority.

Does **not** imply, and is not implied by, C. A cryptographically exact binding
to the wrong user's account is a C pass and a D failure. This separation is the
reason the model has seven properties instead of three.

### E. Execution-Boundary Integrity

*Can the protected side effect be reached only through the controlled path?*

In scope: credential custody, whether the enforcement point holds the only
usable credential, alternative API keys or service accounts, direct SDK or
network access from the agent or runtime, and any other bypass path to the same
effect.

Does **not** follow from the existence of a pre-tool hook, an interceptor, or a
wrapper. A hook is an enforcement boundary only if the effect is unreachable
without it. Evidence for this property is an argument about *credential
topology*, not about hook correctness, and it is the property most often
assumed rather than tested.

Because that argument is easy to make and hard to falsify, E is the one
property with a prescribed evidence shape. See §9.

### F. TOCTOU Resistance

*Can the conditions that were approved change between authorization and
execution?*

In scope: time-of-check versus time-of-use, stale approvals, approval expiry,
state or target changes after approval, re-evaluation immediately before
dispatch, concurrency across threads, processes and hosts, distributed races on
shared single-use state.

Does **not** follow from pre-dispatch validation alone. Validating at time T
demonstrates F only for the interval between T and the dispatch, and only for
the concurrency scope the evidence actually exercised. Single-process evidence
does not establish multiprocess behaviour.

### G. Effect Verification

*Does the system verify the actual external effect after execution?*

In scope: authoritative state read-back, expected versus observed
postcondition, and an explicit vocabulary that separates *verified*,
*mismatched*, *not observable*, *verifier failed* and *unsupported*.

Does **not** follow from: an HTTP 2xx, a tool returning without raising, an
agent's own report of success, or an audit log entry. A record that dispatch
occurred is evidence about the caller, not about the world.

---

## 2. Statuses

| Status | Meaning |
|---|---|
| **PASS** | Concrete, relevant, sufficient evidence that directly exercises the property, at evidence tier RESOLVED (§3). |
| **UNTESTED** | The system may well have the property; the available evidence does not demonstrate it. A missing test is never a FAIL. |
| **OUT OF SCOPE** | The implementer explicitly does not claim the property. This is a legitimate and useful answer, not a negative grade. |
| **FAIL** | Concrete evidence that the property does **not** hold under a tested condition. Used conservatively and only with a reproducible reference. |

Two rules do most of the work:

1. **Absence of evidence is UNTESTED, never FAIL.**
2. **A stated non-claim is OUT OF SCOPE, never FAIL.** Narrow claims are the
   behaviour this model is trying to encourage, and penalising them would
   invert the incentive.

A status may be **partial**, written `PASS (scope: ...)`. A partial PASS must
name the scope it holds within, and the remainder of the property is carried as
UNTESTED in the same row rather than silently absorbed.

## 3. Evidence tiers

Every row records how the assessor obtained the evidence:

| Tier | Meaning |
|---|---|
| **RESOLVED** | The assessor read the named test, fixture, artifact or code at a stated revision. |
| **REPORTED** | The implementer described the evidence; the assessor could not resolve it to an artifact. |
| **NONE** | No evidence was offered. |

**PASS requires tier RESOLVED.** A property whose only support is REPORTED is
recorded as UNTESTED, with the implementer's claimed status noted in the row.
This is a statement about what the assessment could verify, not an accusation:
one resolvable reference converts the row. Recording it this way keeps the
model honest when it is applied across organisational boundaries, where the
assessor usually cannot see the other system's test suite.

## 4. Minimum requirements for PASS

A PASS row must carry all of:

1. A reference an independent reader can open: test path and test name,
   fixture, result artifact, or code path plus revision.
2. **Direct exercise of the property.** A test that would still pass if the
   property were removed is not evidence for it.
3. A declared scope: process model (single-process, multi-process,
   distributed), trust assumptions, and whether the effect was simulated or
   real.
4. **A caveat naming what the evidence does not cover.** A PASS with no caveat
   is treated as an unreviewed row.

## 5. Scope declaration

Each assessment states, once, for the whole system under assessment: the
version or commit assessed, the process and deployment model the evidence
covers, whether external effects were real or simulated, and which properties
the implementer explicitly does not claim. An assessment without a scope
declaration is incomplete.

## 6. Prohibited aggregation

The seven statuses **must not** be combined into a single score, grade,
percentage, star rating, "conformance level", or the word *secure*. There is no
weighting, because the properties are not commensurable: for one deployment E
dominates, for another G does.

A system may state "PASS on A, C and F, at the declared scope". A system may
not state "5/7 conformant" or "Agent Authority Conformant".

Equally prohibited: presenting a comparison of two assessments as a ranking.
Different systems legitimately choose different scopes, and OUT OF SCOPE rows
are not deficits.

## 7. Applying this to a new runtime

1. Obtain a scope declaration from the implementer, including explicit
   non-claims.
2. Ask for the single most authoritative artifact per property. Ignore README
   text, architecture prose and marketing.
3. Resolve what you can; mark the rest REPORTED or NONE.
4. Fill one row per property with status, evidence tier, reasoning and caveat.
5. Send the draft to the implementer and record their disagreement in the
   document rather than resolving it silently.

Step 5 is the acceptance test for the model itself. If an implementer reads
their own rows and says *"yes, this describes exactly what I proved, what I did
not prove, and what I am not trying to solve"*, the model worked. If they
recognise nothing, the property definitions are wrong, not the implementer.

## 8. Known limitations of v0.1

- The seven properties are asserted to be separable, not proven exhaustive.
  Availability, cost control, rate limiting, data minimisation and rollback are
  not covered.
- E now has a prescribed measurement procedure (§9), added after this list was
  first written. The underlying difficulty is unchanged: E is a claim about
  absence, so the procedure bounds the claim rather than proving it. The
  residual limitation is that an E PASS is only ever as wide as the declared
  agent zone and the attempted bypass classes, and both are chosen by the
  assessor.
- The procedure for E is asymmetric across an organisational boundary: its
  static half needs source access. Assessing a third party will usually produce
  bypass results with an UNTESTED topology, which is a weaker row than a
  self-assessment can produce. This compounds the public-test-suite bias noted
  below.
- The model assesses *evidence*, so it systematically favours systems with
  public test suites. That bias is intentional but should be stated whenever
  results are shown.
- No inter-assessor agreement study has been done. Two assessors may
  legitimately disagree on where C ends and D begins for the same artifact.
- v0.1 has been applied to exactly two systems, one of them the authoring
  repository. Reusability is a hypothesis at this point, not a demonstrated
  property. See `docs/benchmarks/aegis-remora-crosswalk.md`.

## 9. Measurement procedure for E

The other six properties are demonstrated by a test that fails when the
property is removed. E has no natural test of that shape, because it is a claim
about *absence*: that no second path to the effect exists. Absence cannot be
tested directly, so this section prescribes what an E assessment must contain
instead. An E row without both halves is recorded as UNTESTED.

**Half one, declared topology.** A machine-readable register listing every
credential that reaches, or authorizes, a protected effect. Per entry: the
credential, its class, the component that holds it, the authorized path, and an
explicit reachability claim. The register must be checked against the code
rather than maintained by hand. Three drifts must fail the check: a credential
the code reads but the register omits, a register entry nothing reads any more,
and a reader set that no longer matches the code. A register that cannot go
stale is the difference between a topology and a diagram.

The reachability claim is made falsifiable by declaring an **agent zone**: the
set of modules agent-controlled code can reach, given as roots plus their
transitive import closure. A credential declared unreachable must not be read
inside that closure. The zone declaration is the load-bearing part of the
claim, and the assessment must state the reasoning for the chosen roots and
what changes if they are drawn wider.

**Half two, bypass attempts.** A suite of named attempts to reach the effect
without the controlled path, each recording what actually happened. Five
attempts are the minimum:

1. dispatch without authorization;
2. dispatch of an unwrapped or unregistered tool name;
3. extraction of the guarded callable from the enforcement point;
4. reading the credential from a shared process;
5. reaching the effect through an already authenticated client, pool or
   subprocess.

**Attempts that succeed are recorded as successes.** This is the rule that
makes the procedure worth running. A bypass suite that reports only refusals is
evidence about the refusals it chose to attempt, and E is precisely the
property where that substitution has gone unnoticed. A demonstrated bypass with
a stated architectural reason is a stronger E row than an unbroken row of
green.

**Reporting.** An E status is the pair, never the static half alone, written as
`PASS (scope: ...)` with the register's limits reproduced. The procedure has
two structural properties an assessor must state:

- It is **asymmetric**. Half one needs source access; half two needs only a
  running endpoint. Assessing a third-party system will usually yield half two
  only, which is UNTESTED for the topology and a real result for the attempts.
- It **cannot prove absence**. A static import scan that misses an edge shrinks
  the zone, so its failure mode is a missed finding, not a false accusation.
  A PASS therefore means *no demonstrable alternative path within the declared
  zone and the attempted classes*, and must be written that way.

---

## Revision note

The version stays at v0.1. Nothing in §1 changed: the seven property
definitions, their separability, and the inferences each one forbids are
untouched, and any assessment written against the original text remains valid.
What §9 adds is an evidence requirement for one property, which raises the bar
for a future E row rather than reinterpreting a past one.

Two things §9 deliberately does not settle. It does not act on the proposal in
`docs/research/adjacent-systems-crosswalk-v2.md` to record `E2` as a declared
scope under E, or to split F into `F1` and `F2`; those are vocabulary changes
and still await review. E also stays incommensurable with the other six
properties, so §6 continues to apply in full.
