# REMORA-Prime: gap analysis and proposed architecture

Status: proposal. Nothing in this document is implemented, and no claim here
is evidence about REMORA as it stands today.

## How to read the statements below

Three classes of statement appear, and they are not interchangeable.

Grounded statements trace to something committed in this repository: a
register entry, a test, a measured artifact, a CI verdict. The anchor is
named.

Assessed statements are a reading of the design from the code and documents.
No artifact backs them. They are reviewer opinion and can be wrong about
details.

Proposed statements describe a system that does not exist. Every number in a
proposal is a target to be falsified, never a result.

The figures used for framing, 26.6 % legitimate autonomy and SHADOW_ONLY
status, are taken from the current operating posture. They are not
re-derived here.

## 1. Gap analysis

REMORA today is a decision system that has not yet become an enforcement
system. A decision system answers whether a call should be allowed. An
enforcement system answers whether an effect did not occur. The seven gaps
below are consequences of sitting on the first side of that line.

### G-1. The safety floor is carried by refusal, not by understanding

Assessed. The floor is hard blocks rather than consensus or entropy. That is
a defensible engineering choice and it is also a ceiling. A hard-guard floor
generalises by pattern, so it stops what someone anticipated and wrote down.

A measured wrong-call rate is therefore a statement about a fixed evaluation
distribution. It is not a statement about an adversary, because an adversary
does not sample from the benchmark. The repository states its BFCL result
carefully. The risk is in how a reader compresses it, not in how it is
written.

Closing this requires an adaptive-adversary evaluation where the attacker
sees the policy bundle and iterates. Until that exists, the strength of the
floor is unmeasured rather than high.

### G-2. Single-call governance cannot see a composed attack

Assessed, and the deepest gap. Every call can be individually innocuous
while the trajectory is harmful. Read a config file, read a credential
store, write a log, make an outbound request. Each passes a per-call check.
The composition is exfiltration.

Draining an account is rarely one transfer of everything. It is several
legitimate-looking transfers under a documented threshold.

REMORA primitives are per-call by construction. The `ExecutionLease` binds
one call, the nonce makes redemption one-shot, the decision envelope records
one decision. These are strong per-call primitives. None of them carries the
notion that this is the fourth read of a secret-shaped object in ninety
seconds by an agent whose task was to summarise a ticket.

This is the widest gap between a research prototype and a system that stops
an account being drained.

### G-3. The evidence covers authorisation, not effect

Grounded. The APS action-result review states the general form: a recorded
`effect_ref` does not establish an external effect. The same limit runs
through REMORA. The system knows that it issued a lease and that a lease was
redeemed. Whether money moved, or a row was deleted, sits outside the
evidence chain.

For governance that is survivable. For safety it is the difference between a
seatbelt and a receipt stating that a seatbelt was issued. Rollback,
compensation, blast-radius accounting and incident forensics all need
effect-level evidence.

### G-4. Utility is the real adoption blocker

Given from the current posture. Autonomy at 26.6 % means roughly three of
four legitimate actions are escalated. No operations team sustains that. The
layer gets disabled or routed around, and a safety floor at zero deployment
protects nothing.

The implication is worth stating directly. A safety system with poor utility
is a safety system that gets turned off. Utility is not the commercial
concern balancing the safety concern. It is a safety property.

The cause is structural. Deterministic matching against declared intent is
precise and brittle. It refuses what it cannot prove, and legitimate work is
mostly composed of things nobody declared in advance.

### G-5. No live production evidence

Grounded, through the SHADOW_ONLY profile. The repository is scrupulous
about this. The cost is that every behavioural claim concerns replay and
benchmark, so the failure modes that appear only in production stay unknown.
Clock skew across services, partial failure mid-lease, operators approving
under time pressure, and a review queue with four hundred items in it are
all unexercised.

The durability work shows the risk is understood. A one-time-grant ledger
that was replayable until recently, in a tree built this carefully, supports
a general claim: the unexercised paths are where the defects are.

### G-6. The trusted computing base is large

Assessed. The code that must be correct for the safety argument to hold is
large. It includes the policy engine, the enforcement gate, lease issuance
and verification, the nonce store, the signing path, the dispatcher, and the
API surface around them.

The 2026-09-21 mutation sweep measured 294 named surviving mutants across
four of those modules, at an 84.6 % kill rate on covered lines. That is
acceptable as engineering. It is not a formal argument, and it indicates
what a formal argument would cost at the current size. A kernel this large
cannot be machine-checked. Either it shrinks to a few hundred lines, or
formal verification stays aspirational.

### G-7. The authority model assumes a single agent

Assessed. Authority binds to actor, tenant, task and runtime identity. No
construct was found for delegating a strictly weaker authority to a
sub-agent for the duration of one sub-task, with revocation following the
parent. Nested agents will arrive regardless. Retrofitting delegation into a
flat authority model is the historical route to confused-deputy defects.

### Claims that are understated

The claim register and the negative-results discipline are stronger than
most published work in this area, and they are not presented as a
contribution. A governance system whose own claims are machine-checked
against artifacts is itself an argument about how the field should work.

Custody separation and exact-call binding are the substance of the design.
The signer is not the executor, and the lease binds the resolved call rather
than a description of it. Comparable toolkits mostly bind a policy decision
and trust the caller to execute what it asked about.

Fail-closed handling of missing evidence is correct here and commonly wrong
elsewhere. An absent binding is refused rather than treated as a wildcard,
so upgrading a check does not silently amnesty everything issued before it.

### Ranking

Ordered by cost to the goal of stopping an agent from draining an account or
destroying production infrastructure:

1. G-2, trajectory blindness, because the attack is the composition.
2. G-3, no effect evidence, because damage that is not observed cannot be
   bounded.
3. G-4, utility, because a floor that gets disabled protects nothing.
4. G-1, unmeasured floor strength, because no adaptive adversary has tested
   it.
5. G-6, kernel size, because it blocks the formal argument.

G-7 and G-5 are real and later.

## 2. Thesis

The current thesis concerns decisions. A deterministic pre-execution overlay
decides an action for each tool call and records hash-chained evidence. Its
unit is the call and its guarantee is that a decision was made and recorded.

The proposed thesis concerns authority as a consumable resource.

> An agent's authority to affect the world should be a finite, attenuating
> and revocable resource. The agent spends it. It is not a permission the
> agent is repeatedly granted.
>
> A minimal kernel decides nothing about intent. It enforces four
> invariants: no effect without an unspent capability; no capability beyond
> what its parent held; no capability that outlives its revocation; every
> effect accounted against a declared budget. Everything else proposes, and
> cannot widen what the kernel permits.

Five consequences follow, each answering a gap above.

Permission becomes budget. A permission check has no memory, so it cannot
answer how much an agent has already done. A budget is consumed. The fourth
transfer fails because the envelope is empty, not because it looked
different from the first. This addresses G-2 without requiring the system to
recognise the attack.

Decision evidence becomes effect evidence. The unit of record changes from a
decision having been made to an effect having occurred or provably not
occurred. Unresolved effects become a first-class state with a deadline.
This addresses G-3.

Monolithic policy becomes a kernel plus proposers. The kernel is small
enough to specify formally and to audit by reading. Intent matchers,
language-model proposers and learned thresholds sit outside it and can only
narrow what the kernel permits. This addresses G-6 and G-4 together, because
a proposer that cannot widen authority is a proposer that can afford to be
generous.

Refusal becomes attenuation. The escalation binary spends operator attention
whenever the matcher is unsure. Attenuation adds a third move: grant the
action under a strictly smaller capability, with narrower scope, shorter
life, tighter budget, and reversible effects only. Most escalated work is
unproven rather than dangerous.

Flat actor identity becomes delegable capability. Authority becomes an
object that can be attenuated and passed to a sub-agent, with revocation
propagating through the derived tree. This addresses G-7 using a known
result from capability-system literature.

The thesis claims that a bounded set of invariants over capability, budget
and effect can be stated precisely, machine-checked at the kernel level, and
enforced at runtime with evidence an auditor can replay.

It refuses to claim that the system knows which actions are harmful. The
design exists to make safety independent of that judgement, by bounding what
being wrong can cost.

## 3. Architecture

### A. Core execution kernel

The size constraint comes first. The kernel must be small enough that one
person can read all of it in an afternoon and a model checker can exhaust
its state space. The target is under 1,500 lines, with no input or output,
no policy evaluation, no model, no network, and no clock of its own.
Anything that cannot meet that bar lives outside the kernel by definition.

The authority primitive is an object capability, an unforgeable reference
that is the authority rather than an index into an access-control table. The
`ExecutionLease` already supplies most of this. Derivation, attenuation and
budget are missing.

A capability carries:

- a unique identifier, and the identifier of the capability it derives from
- the exact effect class permitted, and the resolved call identity
- a counted budget and a half-open validity interval
- the issuer, and the distinct executor permitted to redeem it
- whether the effect has a compensating action

The attenuation rule is the load-bearing invariant. A derived capability has
a scope that is a subset, a budget that is a sub-budget, a validity that is
a sub-interval, and reversibility no weaker than its parent. Derivation can
only shrink. This is a partial order, and every delegation edge must be a
step down it. No operation widens.

Authority is held rather than checked. The question of whether an agent
could ever perform an action becomes a reachability question over a finite
derivation tree, which is answerable. Today it is a question about whether
some future policy evaluation might permit it.

A capability with a budget is affine. It can be used at most as many times
as it has budget, and a use that is not recorded is a use that did not
happen. The implementation language does not need linear types. The ledger
must enforce what linear types would have enforced.

Exact-call binding is already strong. The lease binds the resolved call and
the nonce makes redemption one-shot. Three additions are proposed. Bind the
resolved specification identity, so a capability issued under one version is
never redeemable under the next, and an absent binding is never a wildcard.
Bind the executor instance, so a stolen capability is useless to a different
worker in the same tenant. Make the anti-replay ledger a kernel object
sharing one durable ordered log with the effect record, because a one-shot
guarantee with a volatile ledger holds only until restart.

Custody separation already puts the signer apart from the executor. Two
additions are proposed. The component that decrements a budget should be
neither the issuer nor the executor, so a compromised executor cannot replay
its own spend. Any capability whose effect is both irreversible and above a
declared budget threshold should require two independent signers.

The effect lifecycle is the largest missing piece. States run from
authorised to dispatched, and then to settled, failed or unknown. Unknown is
a first-class pending state carrying a deadline rather than an error.

Four rules make that record evidence rather than bookkeeping. A capability is
spent at dispatch, never at settlement, because spending late leaves a
double-spend window. Settlement requires an effect receipt produced by the
target system, such as a transaction identifier or a resource version;
a dispatcher asserting success is not a receipt. An unknown effect ages into
an operator-visible reconciliation obligation and counts against blast-radius
budgets as if it had happened. Effects declare a compensating action at
authorisation time or are classified irreversible.

The hard-guard floor should become a declarative invariant set that the
kernel evaluates and the verifier checks, with runtime and proof reading one
source. Five invariants are proposed as the complete kernel set:

1. No effect without an unspent capability bound to exactly that call.
2. No capability whose scope, budget, validity or reversibility exceeds its
   parent.
3. No redemption of a capability whose revocation preceded it in log order.
4. Every dispatched effect appears exactly once in the effect log, and its
   budget decrement is atomic with that appearance.
5. Every terminal effect state is justified by evidence of the declared
   class, or is unknown with a live deadline.

Everything the current floor does should be expressible as policy over these
invariants. A guard that cannot be expressed that way belongs outside the
kernel, as a proposer that narrows.

The present floor is as strong as the union of the rules someone wrote. The
proposed floor is a property of the structure, and it holds for effects
nobody anticipated.

### B. Trajectory and path governance

The obvious design is a trajectory classifier that learns which sequences
are harmful. That should not be the primary mechanism. It inherits the
weakness of the current floor, and it adds an attack surface, because a
classifier over agent-controlled history can be poisoned by an agent that
chooses its own history.

The improvement over the path-policy literature is not better path
recognition. It is making the path bounded whether or not it is recognised.

The primary mechanism is a budget on the derivation tree. A task begins by
minting a root capability with an explicit budget. Every sub-capability
draws from it. The budget is a vector over dimensions an operator can reason
about: irreversible effects, monetary value, distinct principals touched,
secret-class objects read, external destinations written, and objects
deleted.

This answers the several-transfers-under-a-threshold case directly. Each
transfer is individually permitted and the fourth has no budget. The system
never had to notice that the sequence was an attack.

The resulting property is stronger than it appears. For any trajectory,
reachable or not, anticipated or not, the total effect is bounded by the
root budget. That is a statement over all paths, which a per-call system
cannot make.

The secondary mechanism is label propagation over cross-call data flow.
Budgets bound magnitude, not combination. Reading a secret and writing to an
endpoint may each be within budget while the composition is a breach. Every
object read attaches a label to the returned data, labels flow into calls
whose arguments derive from labelled data, and a capability declares which
labels it may accept as arguments.

The limit must be stated in the claim register on the first day. Label
propagation through a language model is unsound, because the model can
launder a secret by paraphrasing it. The label system is defence in depth
that catches mechanical cases. The guarantee comes from the budget on
external destinations, which holds regardless of laundering.

Temporal reasoning stays outside the kernel. The kernel has log ordering and
interval validity, which suffice for its invariants. Rate limits, cooldowns
and time-of-day rules are proposers that narrow. Clock-dependent invariants
are where distributed-systems proofs fail, so the counted form is preferred
over the timed form wherever both would serve.

Real deployments observe part of the path. Budgets bind the mediated path only. A deployment must
declare which effects fall outside mediation. A deployment that cannot say which effects are
outside mediation cannot make a trajectory claim, and the system should
refuse to issue a root capability in that configuration.

Compared with current REMORA, this makes a statement about all paths rather
than each call. Compared with path-policy work, it is less expressive and
enforceable before each call with no lookahead. Compared with
monitor-the-trajectory systems, it has no false-negative rate for the
property it bounds, and its imprecision is visible and tunable. Compared
with per-call policy engines, it supplies a property that no quantity of
additional rules can produce.

### C. High-utility semantic authority

Deterministic intent matching answers a binary question, and legitimate work
mostly matches nothing declared in advance. The matcher is correct and the
system is unusable, which is the classic precision-over-coverage failure.
Escalated work is overwhelmingly unproven rather than suspicious, and the
architecture has no way to say so.

The proposed move replaces the binary with a lattice of attenuated grants.
The question becomes what the largest justifiable capability for this call
is, and whether it is large enough to be useful.

An exact match to a declared intent with grounded arguments earns a full
capability. A reversible effect with grounded arguments and no intent match
earns a capability with a pre-registered compensation and a small budget.
Read-only work within the already-touched object set earns a capability with
no budget decrement. Read-only work elsewhere in the tenant decrements the
read budget. Irreversible effects, label-boundary crossings and over-budget
requests escalate, because no attenuation makes them safe.

Nothing here widens what an irreversible action may do. The utility comes
from treating reversible and irreversible actions as different questions.

The dependency is the reversibility split. A delete with soft-delete is
reversible and without it is not. The classification is deployment-specific,
must be declared per tool, and must default to irreversible when undeclared.
This repository already demonstrates the failure mode, at a smaller scale:
before 2026-09-22 an undeclared `action_type` took the reversible weight in
the credal risk model, so the escalation depended on the spelling.

A language-model proposer is acceptable under a shape that makes its output
checkable. The proposer emits a derivation receipt rather than a decision. A
receipt is a structured argument for why a call follows from the task, with
each argument value traced to a task field, a prior verified output, a
constant, or the model itself.

A deterministic checker then validates the receipt. Every argument value
must trace to a declared source. Model-generated values are permitted only
where the tool contract marks a parameter as free text, and never for
identifiers, amounts, destinations or scopes. The claimed effect class must
match the tool contract.

The inversion matters. The model proposes and a deterministic checker
validates the structure of the proposal rather than its semantics. A
hallucinating model produces a receipt that fails to trace, which is a
mechanical failure rather than a judgement call.

Argument grounding is where wrong-call acceptance lives. The dominant
failure is the right tool with a hallucinated argument, such as an account
number that appears nowhere in the task. The rule should be strict: every
identifier-shaped argument must appear verbatim in the task, in a prior
verified output, or in a declared constant set. Prior verified outputs count
as sources, so the lookup-then-act pattern works while a remembered
identifier fails.

The target pair of at least 85 % autonomy on reversible effects at no more
than 0.5 % wrong-call acceptance is a hypothesis, not a prediction. It
should be pre-registered before the work starts, measured on a published
corpus, evaluated against an adaptive adversary that sees the tool contracts
and the grounding rules, and reported per effect class. An aggregate hides
the only case that matters.

The kill criterion is stated in advance. If autonomy on reversible effects
cannot exceed 70 % at the stated wrong-call bound, attenuation has failed
and the escalation binary should be kept.

### D. Multi-agent and hierarchical governance

Delegation is derivation. A parent spawning a sub-agent derives a capability
from one it holds, and the attenuation rule applies unchanged.

Three consequences follow. A sub-agent can never exceed its parent, by
construction rather than by policy, because no derivation operation widens.
Budget is drawn rather than copied, so a fleet cannot multiply its blast
radius by spawning. Derivation depth and total derived-capability count are
bounded from the root.

Revocation removes the entire subtree derived from a capability. Two
properties are in tension. Revocation must be ordered against redemption,
where earlier means log position rather than wall-clock time, because
distributed clocks make the alternative unprovable. Revocation must also be
prompt, since a slow propagation is a window of authorised damage.

Ordering is free and promptness is paid for. A revocation epoch checked at
redemption is correct and only as prompt as the redemption path. Pushing
revocation to every executor costs more. The recommendation is to start with
the cheap design, measure the propagation window, and publish it as a known
bound. A stated window is honest engineering; an unstated one is a
liability.

All effects from one derivation tree land in one effect log keyed by root
capability. That supports the two queries an operator needs during an
incident: what this task has done across every agent it spawned, and what
authority remains live under this root. Revoking the root ends all of it in
one operation. A governance system whose answer to stopping an agent is to
restart the workers is not a control.

The confused-deputy case needs an explicit rule. An agent acting on a
request must act under a capability derived from the requester, never under
its own. If a high-authority agent holds authority the requester lacks, it
may not use that authority to serve the requester. This belongs in the
kernel rather than in framework convention.

One fleet-level addition is proposed: an organisational budget that all root
capabilities draw from. This expresses limits such as a cap on irreversible
production changes per hour across every agent. It needs a clock, so it sits
outside the kernel as a proposer that can refuse to mint roots.

### E. Learning under governance

One rule governs the whole design. A learned parameter may narrow what the
kernel permits and may never widen it.

Under that rule a fully compromised learning system can cause denial of
service and cannot cause an unsafe action. The property belongs to the
structure, so it does not depend on the learning system being trustworthy or
even correct.

Learning may not touch budgets, scopes, the attenuation order, or the
reversibility classification. What remains is still valuable: prioritising
the escalation queue, improving proposer quality, recommending budgets to a
human, and surfacing anomalies for review. Budget recommendation is never
budget setting, and anomaly surfacing is never an input to a grant.

A change outside that list passes through the same machinery as any other
governed action. The learner emits a proposed policy delta with the evidence
for it, naming which decisions would change over which replay corpus. The
delta is evaluated in shadow against a held-out corpus the learner has never
seen. A human approves, and the approval is itself a governed, signed and
logged action. The delta then activates with a staged rollout and an
automatic revert bound to a pre-declared threshold.

Each learned parameter carries five fields in the register:

- the corpus it was fit on, by hash
- held-out performance with an interval
- the date of last validation
- the blast radius if the parameter is wrong
- the human who approved it A parameter whose
validation has expired reverts to its conservative default rather than
continuing on stale evidence.

Three risks remain even under the narrowing rule. Training-data poisoning
can cause denial of service, and a governance layer that refuses everything
gets disabled, so autonomy floors should trigger human review rather than
silent degradation. The approval step can become a rubber stamp, so a delta
must be presented as the specific decisions that change. Many individually
narrow changes can drift, so the cumulative delta should be re-evaluated
against the original baseline rather than only against the previous step.

### F. Formal and evidence layer

The achievable formal work concerns concurrent-protocol properties rather
than the code. Attenuation as a partial order, budget conservation across
interleavings, no redemption after revocation, and one-shot redemption under
crash and retry are all within reach of a model checker. Atomicity of the
effect-log append with the budget decrement is specifiable, and binding that
spec to the implementation is harder. A refinement proof from a Python
kernel is a multi-year project. Correctness of intent matching is not
formalisable, because the intended behaviour has no formal definition.

The recommendation is TLA+ as the primary tool, because the properties that
matter concern interleavings, crashes and ordering, and TLC produces
counterexample traces an engineer can read. Alloy suits the capability
algebra, which is a relational structure, and will find derivation
counterexamples cheaply. Model-based conformance testing is the bridge:
generate traces from the specification, replay them against the
implementation, and assert the same states.

A defensible claim is a model-checked protocol with a conformance-tested
implementation. A claim of a formally verified system would be false.

Four things are required, and the cost should be visible before anyone
commits. The kernel must be isolated into a module with no input or output.
The specification must be written from the invariants rather than
transcribed from the code, because a spec derived from the code proves only
that the code equals itself. The checked state space must cover concurrency,
crash and revocation-during-redemption, with bounds stated, since TLC
results are bounded. A conformance suite must bind implementation to
specification in CI, failing the build on drift. The estimate is three to
six months of focused work, and it is unreachable unless the kernel shrinks
first.

The claim register should gain a `verification_method` field with a fixed
vocabulary covering measured, model-checked, tested, argued and assumed
claims. Bounds should be mandatory for model-checked claims, so that the
recorded claim is the bound rather than the word verified. Claims should
expire, degrading to stale when their evidence has not been regenerated
against current code within a declared window. The 2026-09-21 mutation
finding is the argument for expiry: a gate that had silently stopped running
looked exactly like a gate that was passing.

The negative-results discipline should gain one category, covering
architectural directions considered and rejected, with what would change the
decision. That record prevents a future maintainer from re-walking a dead
path.

## 4. Roadmap

Every phase carries a kill criterion. The kill criteria are the part to take
seriously, because a roadmap without them is a wish list.

Phase 0 runs for roughly four months and formalises and shrinks the kernel,
with no new features. It delivers the five invariants written precisely and an
Alloy model of the capability algebra. It also delivers a TLA+ specification
of issue, derive, redeem and revoke under crash and concurrency, the kernel
extracted into a module without input or output, and a conformance suite
generating traces from that specification. It succeeds when the model checker finds no
counterexample at stated bounds, the kernel is under 1,500 lines, and the
conformance suite fails CI on drift. It is killed if the kernel cannot be
reduced below roughly 3,000 lines without losing required behaviour, in
which case the formal direction is not viable at this architecture.

Phase 1 overlaps and runs to about month nine, delivering trajectory budgets
and the utility fix together, because the utility fix needs budgets to be
safe. It delivers budget vectors with atomic decrement, the effect lifecycle
with receipts and first-class unknown, attenuated grants replacing the
escalation binary, derivation receipts with mechanical argument grounding,
and a published corpus of legitimate agent tasks. It succeeds at the
pre-registered autonomy and wrong-call targets with budget conservation
holding under fault injection. It is killed if reversible-effect autonomy
cannot pass 70 % at the stated wrong-call bound. The reversibility
classification should be tested against ten real tools in month three,
before anything is built on it.

Phase 2 runs from about month eight to month fifteen and delivers
multi-agent governance and production evidence. It delivers derivation,
delegation, propagating revocation, a cross-agent effect log keyed by root,
fleet budgets, and a controlled pilot with real traffic, operators and
effects on a bounded domain. It succeeds with ninety days of operation, zero
unauthorised effects, a published incident log including near-misses, a
measured revocation window, and an escalation load within a declared target.
It is killed if operators route around the system, regardless of what the
corpus measurements said. This phase is where the project becomes real or
stays a paper.

Phase 3 runs to about month twenty and delivers verification and external
replication. It covers the full specification including multi-agent
derivation, and puts model-based conformance in CI. It adds an independent
party reproducing the headline results from published artifacts alone, and
an adaptive-adversary evaluation against a red team that sees the policy
bundle. The strongest possible
outcome is the adversary defeating intent matching while failing to exceed
the budget bound. It is killed, as a stop-everything finding, if an adaptive
adversary can exceed a root budget.

Phase 4 runs to about month twenty-four and delivers a production profile
with stated operational requirements. It adds a stable SDK with a versioned
capability format, a migration path from shadow mode, and a documented
threat model naming residual risks. It closes with a security review by
people who did not build the system. It succeeds with a deployment run by an external party. It
is killed if no external party will run it, in which case the thesis may be
right and the product is not viable. Both outcomes are worth publishing.

Four sequencing constraints apply. Phase 0 gates everything, because
building on an unformalised kernel means formalising twice. The Phase 1
utility work gates Phase 2, because no operator pilots a system that
escalates three calls in four. Phase 3 formal work should follow the pilot,
because production contact will change the specification. The
adaptive-adversary work could start at any time and is the cheapest
high-information experiment available.

## 5. Proposed experiments

Each experiment is designed so that failure is informative.

E1 tests whether the budget holds where judgement fails. A red team with
white-box access attempts to exceed a declared root budget across a
multi-step task, and is explicitly permitted to defeat the intent matcher.
Success is zero budget violations across at least one hundred adversarial
episodes while the matcher is defeated in a meaningful fraction. Failure is
any single budget violation.

E2 runs the account-draining scenario against a sandboxed financial API with
real balances and real irreversibility inside the sandbox. Success is that
total value moved never exceeds the declared budget across every attack
strategy. Failure includes any strategy that moves more, and any strategy
that succeeds by making the governance layer unavailable.

E3 measures autonomy at fixed safety on a published corpus, comparing
current REMORA, the proposed system, an ungoverned baseline, and at least
one competing toolkit. Success is the pre-registered target with per-effect-
class breakdowns and a public corpus. Failure is autonomy below 70 %, or a
number that holds only on anticipated tasks.

E4 measures revocation under concurrency. A fleet under one derivation tree
has its root revoked while redemptions are in flight, under partition and
worker crash. Success is zero redemptions ordered after the revocation
succeeding, with a measured and published propagation window. Failure is any
post-revocation redemption, or a window that cannot be bounded.

E5 runs a confused-deputy gauntlet, in which a low-authority agent tries
every available route to have a higher-authority agent act on its behalf.
Success is that every attempt is refused or executes under the requester's
attenuated authority. Failure is one successful escalation.

E6 tests effect-evidence integrity by injecting faults between dispatch and
receipt, including targets that succeed without acknowledging, acknowledge
without acting, acknowledge twice, or acknowledge after a timeout. Success
is a correct terminal state or an unknown that ages into an obligation, with
no settled state without a genuine receipt and no double spend. Failure is
any silent misclassification.

E7 tests that learning cannot widen. An adversary controls the training data
and optimises freely over a year of simulated operation. Success is that no
reachable configuration permits an action the original kernel refused, where
denial of service is acceptable and escalation of authority is not. Failure
is any reachable widening.

E1 and E3 come first if resources force a choice. One establishes the safety
thesis and the other establishes that anyone would deploy it.

## 6. Open problems and risks

Five problems are unsolved.

Setting the budget is the original problem relocated. Budgets bound damage
only when set correctly, too tight is useless and too loose permits the
attack, and no principled general method is known. The proposal is to derive
budgets from observed legitimate behaviour with a wide margin, and to make
every budget an explicit operator decision with the blast radius stated.
Moving from recognising bad actions to bounding total damage is progress
rather than elimination.

Information flow through a language model is untrackable, because any label
scheme can be laundered by paraphrase. This is a property of the medium
rather than an engineering gap.

Reversibility is not a property of a tool. It depends on target
configuration, elapsed time, and whether anyone has acted on the result.
Since the utility design rests on this classification, it is the most likely
cause of the utility work failing.

The evidence gap at the system boundary cannot be closed from inside the
governance layer. A receipt proves only what the target chose to report, so
the guarantee is conditional on target honesty and should be stated as an
assumption.

Verification of the implementation, as distinct from the protocol, remains
open. Conformance testing narrows the gap between specification and code
without closing it.

Five risks could sink the direction.

The most likely is that nobody deploys the system, so nothing is learned.
Everything in the roadmap depends on real contact, and the highest-value
derisking action is an earlier and smaller real deployment than the plan
requires.

The utility fix may not reach its numbers, leaving an elegant version of an
unadopted system.

Complexity may consume the safety argument. Budgets, labels, derivation,
effect lifecycle, receipts and fleet policy are each justified and may
together exceed what can be verified or operated. The kernel-size discipline
is the only defence and will be under pressure in every design decision.

Model-level control may improve enough that external governance becomes a
niche. This looks unlikely within three years, because model-level control
produces no audit trail for a regulator and cannot be verified by the party
bearing the risk. The audit and evidence angle is the part of the value
proposition most robust to this.

Maintainer concentration is a risk that no architectural decision addresses.
A formal specification helps, because a specification transfers in a way
that judgement does not.

Three outcomes would end the thesis. An adaptive adversary exceeding a root
budget through a route the invariants were meant to exclude means the
structural claim is wrong. Autonomy below 70 % means the utility mechanism
does not work. A kernel that cannot shrink means the formal argument is
unreachable, leaving a well-engineered system with a testing-based assurance
story.

## 7. First thirty days

The actions below are ordered by information gained per day spent.

Classify ten real tools by reversibility, taking two days. If more than
three are ambiguous, the utility mechanism has no foundation and the roadmap
changes.

Run an adversarial test against the current hard-guard floor, taking three
days, without waiting for any new architecture. If the floor proves brittle,
that reprioritises everything below it.

Write the five invariants in precise prose on one page, taking one day, and
land it under `docs/assurance/`.

Build the smallest useful Alloy model of the capability algebra, taking
three to four days, checking that derivation never widens and that
revocation reaches the whole subtree. This is the highest-value technical
action available, because it validates or breaks the core model in under a
week.

Instrument the escalation queue for one week of shadow traffic, recording
per escalation whether the effect was reversible, whether grounding would
have passed, whether an intent was declared, and what the operator decided.
This converts an aggregate into a distribution and tells you how much of the
gap attenuation can reach.

Add effect receipts to exactly one tool path, taking four days, with a
target-produced receipt required for settlement and reconciliation visible.
Doing one properly teaches more than designing all of them.

Draft the TLA+ specification skeleton for issue, derive, redeem and revoke,
taking three days. It need not check yet. The contradiction it exposes
against the implementation is the deliverable.

Publish the gap analysis, taking one day. A project that publishes its own
seven most critical limitations makes a credibility argument that nothing
else can make.

Find one external party willing to run a bounded pilot, starting
immediately, because the sales cycle is longer than the build cycle.

Seed an abandoned-designs register, taking half a day, beginning with
decisions already made and rejected in this repository, and recording what
would change each verdict.

Four things should not happen in those thirty days. Multi-agent work is the
most attractive and the least urgent. A kernel rewrite before the
specification is a guess. Additional tools and integrations do not address
the constraint. An architecture announcement without evidence spends
credibility this project has been careful to build.
