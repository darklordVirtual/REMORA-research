---------------------------- MODULE LeaseRetry ----------------------------
(***************************************************************************)
(* One logical operation in federation-port/v0's runtime (src/runtime/      *)
(* store.ts at 92d5078): admission claims attempt 1 under a lease; a retry *)
(* claims a new attempt when the operation is unknown, failed and          *)
(* retriable, or dispatched with a lease the claiming worker sees as       *)
(* expired; finishAttempt records an attempt's outcome. The provider is    *)
(* idempotent on the operation's key, so it performs the refund at most   *)
(* once. Time is abstract: Tick passes the admission deadline.             *)
(*                                                                         *)
(* Constants select the runtime and the environment:                       *)
(*   ConfirmationFinal  FALSE = the pinned rule (only the latest attempt,  *)
(*                      or a confirmation already recorded, updates the    *)
(*                      operation); TRUE = the patched rule (a             *)
(*                      confirmation from any attempt is final).           *)
(*   ClockSkew          TRUE lets a worker see a live lease as expired     *)
(*                      while its attempt is still running (contract       *)
(*                      section 10: skew between workers is not handled).  *)
(*                      FALSE: a lease is taken over only after its        *)
(*                      attempt has ended or its worker has died.          *)
(*   Outages            TRUE lets an attempt fail to reach the provider    *)
(*                      and say so (failed and retriable, as the simulator *)
(*                      executor does on ECONNREFUSED).                     *)
(*   Crashes            TRUE lets a worker die inside execute() without    *)
(*                      reporting; its lease then expires.                 *)
(*   UncertaintySticky  TRUE: a later attempt's failed-and-retriable sets  *)
(*                      the operation to failed only if every earlier      *)
(*                      attempt also reported failed-and-retriable; if an  *)
(*                      earlier attempt may have reached the provider, the *)
(*                      operation becomes unknown instead.                 *)
(*                                                                         *)
(* This is a model of the abstraction, written to find counterexamples.    *)
(* It is not a proof about the TypeScript runtime; the correspondence is   *)
(* tested by the contract probes, not established here.                    *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS ConfirmationFinal, ClockSkew, UncertaintySticky, Crashes, Outages, MaxAttempts

Outcomes == {"provider_confirmed", "failed_retriable", "unknown"}

VARIABLES
    state,       \* "dispatched" | "provider_confirmed" | "failed" | "unknown"
    retriable,   \* the operation's retriable flag
    closed,      \* closed past the deadline as approval_expired_before_retry
    attempts,    \* the operation's attempt counter
    running,     \* attempts whose worker is still inside execute()
    sent,        \* attempts whose request reached the provider
    refunds,     \* refunds the provider performed (idempotent: 0 or 1)
    late,        \* the admission deadline has passed
    clean        \* attempts that reported failed-and-retriable (never sent)

vars == <<state, retriable, closed, attempts, running, sent, refunds, late, clean>>

Init ==
    /\ state = "dispatched" /\ retriable = FALSE /\ closed = FALSE
    /\ attempts = 1 /\ running = {1} /\ sent = {} /\ refunds = 0
    /\ late = FALSE /\ clean = {}

\* A running attempt's request reaches the provider.
Send(a) ==
    /\ a \in running /\ a \notin sent
    /\ sent' = sent \cup {a}
    /\ refunds' = 1
    /\ UNCHANGED <<state, retriable, closed, attempts, running, late, clean>>

\* The outcomes an attempt can honestly report. If its request got through,
\* confirmed, or unknown when the response was lost. If it never reached the
\* provider, failed and retriable, or unknown when it cannot tell.
Honest(a) == IF a \in sent THEN {"provider_confirmed", "unknown"}
             ELSE IF Outages THEN {"failed_retriable", "unknown"} ELSE {"unknown"}

\* finishAttempt: the attempt row always records its outcome; the operation
\* takes it only under the rule below.
\* An earlier attempt that did not report failed-and-retriable may have
\* reached the provider (it confirmed, it was unknown, or it never reported).
EarlierUncertain(a) == \E j \in 1..(a - 1) : j \notin clean

Finish(a, o) ==
    /\ a \in running /\ o \in Honest(a)
    /\ running' = running \ {a}
    /\ clean' = IF o = "failed_retriable" THEN clean \cup {a} ELSE clean
    /\ IF state # "provider_confirmed"
          /\ (attempts = a \/ (ConfirmationFinal /\ o = "provider_confirmed"))
       THEN /\ state' = IF o = "failed_retriable"
                        THEN IF UncertaintySticky /\ EarlierUncertain(a)
                             THEN "unknown" ELSE "failed"
                        ELSE o
            /\ retriable' = (o # "provider_confirmed")
       ELSE UNCHANGED <<state, retriable>>
    /\ UNCHANGED <<closed, attempts, sent, refunds, late>>

\* A worker dies inside execute(): its attempt never reports.
Crash(a) ==
    /\ Crashes /\ a \in running
    /\ running' = running \ {a}
    /\ UNCHANGED <<state, retriable, closed, attempts, sent, refunds, late, clean>>

LeaseSeenExpired == running = {} \/ ClockSkew

\* claimDispatch, as a retry submits the same request.
Claim ==
    /\ ~closed /\ attempts < MaxAttempts
    /\ \/ state = "unknown"
       \/ state = "failed" /\ retriable
       \/ state = "dispatched" /\ LeaseSeenExpired
    /\ IF state = "failed" /\ late
       THEN \* a retriable failure past the deadline is closed, not dispatched
            /\ closed' = TRUE /\ retriable' = FALSE
            /\ UNCHANGED <<state, attempts, running, sent, refunds, late, clean>>
       ELSE /\ attempts' = attempts + 1
            /\ running' = running \cup {attempts + 1}
            /\ state' = "dispatched"
            /\ UNCHANGED <<retriable, closed, sent, refunds, late, clean>>

Tick == ~late /\ late' = TRUE
        /\ UNCHANGED <<state, retriable, closed, attempts, running, sent, refunds, clean>>

Next ==
    \/ \E a \in 1..MaxAttempts : Send(a) \/ Crash(a)
    \/ \E a \in 1..MaxAttempts, o \in Outcomes : Finish(a, o)
    \/ Claim
    \/ Tick

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ state \in {"dispatched", "provider_confirmed", "failed", "unknown"}
    /\ retriable \in BOOLEAN /\ closed \in BOOLEAN /\ late \in BOOLEAN
    /\ attempts \in 1..MaxAttempts
    /\ running \subseteq 1..MaxAttempts /\ sent \subseteq 1..MaxAttempts
    /\ refunds \in 0..1 /\ clean \subseteq 1..MaxAttempts

\* The property CP-F1 violates. Contract section 4: failed is retriable only
\* when the provider did not perform the side effect, and the closing rule
\* of section 7 rests on that. An operation closed as failed must not have a
\* refund behind it, and once no attempt is running, a performed refund must
\* show as a confirmed operation or as one still open to a retry.
NoClosedFailureWithEffect == closed => refunds = 0

QuiescentStateMatchesEffect ==
    (running = {} /\ refunds = 1) =>
        \/ state = "provider_confirmed"
        \/ (state \in {"unknown", "dispatched"} /\ ~closed)
        \/ (state = "failed" /\ retriable /\ ~closed)
=============================================================================
