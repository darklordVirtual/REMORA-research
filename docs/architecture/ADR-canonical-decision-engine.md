# ADR: Canonical decision engine and the research surface's stated lifetime

- Status: **accepted** (2026-08-25); **retirement gate fired** (2026-08-26)
- Gate update 2026-08-26: the #389 paper reframe landed — the paper's primary
  claims now rest on the governed-execution surface, not on assess. Per §3 of
  the decision, `remora/engine.py` moved CORE → EXPERIMENTAL in the Module
  Stability Index and `/v1/assess` is re-tagged as the research surface in
  the API. The surface stays served and tested (the negative-results record
  depends on it); what changed is its classification, not its behaviour.
  Physical retirement of the route remains a separate, later decision.
- Deciders: repository owner
- Related: issue #296, `docs/product/product_truth_contract.yaml`,
  `docs/architecture/ADR-single-authoritative-execution-path.md`,
  `docs/sdk.md`

## Context

Two decision engines serve two surfaces. The policy core
(`remora/policy/decision_engine.py` behind `/v1/execution/*`) is the
enforcing path: deterministic hard guards first, signed grants, leases, PEP
verification. The multi-oracle consensus engine (`remora/engine.py::Remora`
behind `/v1/assess`) is the research instrument the paper's assess-surface
evaluations run on.

Issue #296 (self-review finding 08-02) recorded the costs of leaving the
relationship unstated: the policy identity hash needed a `surface`
discriminator because the two genuinely decide differently
(`execution_profile=True` makes probabilistic ACCEPT structurally impossible
on one surface and not the other); rate limiting existed only on
`/v1/assess` while idempotency keys existed only on `/v1/execution/*`; and
the error shapes were assumed to differ.

## Decision

**The policy core is the canonical decision engine.** This restates in
engine terms what the product truth contract and the single-execution-path
ADR already say in product terms: the canonical flow runs through
deterministic hard guards and `RemoraDecisionEngine`, and nothing outside it
gates enforcement.

**The consensus engine is a research surface with a stated lifetime:**

1. It never becomes a prerequisite for, or an override of, any enforcement
   decision. This is already load-bearing (the hard-guard floor, the
   execution profile) and this ADR makes it the engine's *identity* rather
   than a property someone might refactor away.
2. It is retained, tested and maintained for as long as the paper's
   assess-surface evaluations and the negative-results record depend on it.
   The multi-oracle work is part of the falsification history
   (NEGATIVE_RESULTS §38 among others), and deleting the machinery would
   orphan the evidence.
3. Its retirement is gated on the paper reframe (#389): when the paper's
   primary claims no longer rest on the assess surface, `/v1/assess` may be
   re-scoped or retired, and `remora/engine.py` moves toward
   EXPERIMENTAL/HISTORICAL in the Module Stability Index in the same change.
   Until that gate, it stays CORE-maintained but frozen in responsibility:
   no new enforcement-adjacent duties accrue to it.

**Cross-surface concerns are shared, not duplicated.** With this ADR:

- the per-tenant rate limiter guards the mutating routes of both surfaces
  (`REMORA_ASSESS_RATE_LIMIT_PER_MIN`,
  `REMORA_EXECUTION_RATE_LIMIT_PER_MIN`);
- idempotency keys are honoured on both decision-producing POST surfaces,
  against the same durable store, namespaced per surface so a key replayed
  across surfaces can never return the other surface's response;
- error sanitisation was verified to be shared already: both routers sit on
  one FastAPI app whose catch-all handler routes every unhandled exception
  through `_safe_error_response` with a correlation id. The execution
  router's `str(exc)` HTTP 409 details are deliberate machine-readable
  refusal codes from the domain exceptions, not leaked internals — bounded
  where they were not (PR #375).

## Consequences

- A reader asking "which engine decides?" has one answer with a reference,
  instead of inferring it from route wiring.
- The `surface` discriminator in the policy identity hash stays: the two
  engines genuinely decide differently, and hiding that would be worse than
  carrying it.
- Consolidating the two engines into one implementation is explicitly NOT
  this decision. It remains possible later, behind the #389 gate; deciding
  canonicality and sharing the middleware concerns removes the operational
  cost of waiting until that is safe.
