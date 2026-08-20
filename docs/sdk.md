# REMORA SDK — the stable integration surface

`remora.sdk` is the *only* Python namespace third-party code should import.
It talks to a REMORA control plane over the versioned REST contract
(`schemas/openapi.json`, drift-gated in CI) and deliberately owns no tool
credentials: policy evaluation, human review, token/lease binding,
enforcement and the audit chain stay server-side. The SDK provides no
bypass operation — but actual non-bypassability is a *deployment*
property: it holds only when REMORA is the exclusive credential-holding
execution path and the agent has no direct route to the governed side
effects.

Everything outside this namespace (`remora.policy`, `remora.enforcement`,
`servers.*`, ...) is internal and may change without notice.

## Install

```bash
python -m pip install -e ".[sdk]"       # client only (adds httpx)
python -m pip install -e ".[api,sdk]"   # + in-process server for the offline demo
```

`remora.sdk` models and errors import without the extra; only
`RemoraClient` needs httpx.

## Stability classification

| Aspect | Guarantee |
|---|---|
| Surface | The 28 symbols in `artifacts/sdk/public_api_v1.json` — nothing else |
| Gate | `tests/test_sdk_public_api.py` fails CI on any unreviewed symbol change |
| Pre-1.0 semantics | Breaking changes are allowed in minor versions, always CHANGELOG-recorded; removals require a deliberate, reviewed snapshot update |
| Additions | New symbols/fields arrive additively; `raw` on result models retains the full response body for forward compatibility |
| Vocabulary | `DecisionAction` is re-exported from the canonical policy enum — the SDK introduces no parallel decision vocabulary |

Deprecations are announced in the CHANGELOG at least one minor version
before removal, and the snapshot diff makes every surface change visible
in review.

## The governed loop

```python
from remora.sdk import RemoraClient, ToolCall, DecisionAction

client = RemoraClient("https://remora.internal", token="...")
result = client.assess(ToolCall(
    tool_name="set_valve_position",
    arguments={"valve": "V-18", "position_pct": 35},
    target_environment="prod",
    intent_ref="WO-1204",
))
if result.action is DecisionAction.VERIFY:
    # a human approves via their own credential, then:
    client.execute(result.review_item_id, ...)
```

`assess` never executes anything. ACCEPT returns a signed single-use
execution token; VERIFY/ESCALATE queue a review item; ABSTAIN returns
neither. Client-declared trust signals (`schema_valid`,
`rollback_available`) can only lower trust, never raise it — with no
server-side evidence even a low-risk read lands on ABSTAIN.

**Lifecycle coverage.** Both branches are redeemable from this client
(issue #36, closed 2026-08-05):

```python
if result.action is DecisionAction.ACCEPT:
    client.execute_accepted(result.execution_token, call)   # same call!
elif result.action is DecisionAction.VERIFY:
    client.execute(result.review_item_id, call)             # after approval
```

`execute_accepted` re-presents the full payload so the server can verify
the token's binding. A different payload raises `BindingRefusedError`
**without** burning the grant; a second redemption raises
`ReplayRefusedError`; an expired token raises `ApprovalExpiredError`. A
deployment-side PEP consuming the token out-of-band remains supported —
the REST path is an addition, not a replacement.

**What would resolve a VERIFY.** Every VERIFY and ESCALATE carries a
machine-readable `ResolutionPlan`, discriminated by `type`:
`human_approval` names the `required_role` and the deadline;
`machine_resolution` names a bounded lookup the engine identified.
ABSTAIN carries **no** plan — no bounded step is known, and promising one
would be a lie. An ESCALATE's `required_role` is always higher than a
VERIFY's: an escalation a normal reviewer may approve is not an
escalation.

```python
plan = result.resolution_plan
if plan and plan.type == "human_approval":
    print(plan.required_role, plan.requirements, plan.expires_at)
```

`reject(review_item_id, reason=...)` records a reviewer's refusal
terminally; the reason is mandatory, because an unexplained refusal
cannot be reviewed afterwards, and a rejected item can never be approved
or executed.

Runnable end-to-end version, offline, zero configuration:

```bash
python examples/sdk_quickstart.py
```

It drives the full loop — honest ABSTAIN, review-routed prod write, the
typed refusal when the agent credential tries to approve its own call,
governed execution, audit-chain verification — against the real ASGI app
in-process.

## Reading a proposal back

Acting on a decision is half the contract; reviewing what happened is the
other half.

```python
view = client.get_proposal(proposal_id)      # decision + current state
trail = client.get_lifecycle(proposal_id)    # ordered event trail
bundle = client.export_evidence(proposal_id) # sections + hashed manifest
```

All three are **projections** over the stores of record (audit chain and
outbox), never a fourth store, so they cannot disagree with what actually
happened. `current_state` is derived for the same reason. They are
tenant-scoped: another tenant's proposal is a 404, not a redacted 200.

`export_evidence` returns the raw mapping on purpose — the manifest hashes
each section over its exact JSON, so re-shaping into typed models would
break independent verification. The manifest makes editing **evident**,
not impossible: a party who rewrites bundle *and* manifest produces a
self-consistent forgery, which is why the audit chain's own verification
travels inside the bundle rather than being replaced by it.

## Verifying that it actually happened

Everything above governs *authorization*: what may run, bound to an exact
payload, under a signed spec. None of it looks at the world afterwards, so
"executed" means only "the dispatcher returned without raising". Closing
that gap is what the effect surface is for.

**The reader stays yours.** REMORA never reaches into your system of
record, because the credentials belong with you. You observe, the SDK
compares, and the record crosses back:

```python
from remora.sdk import build_postcondition, content_digest, verify_effect

spec = build_postcondition(
    tool_id="create_github_issue",
    target_selector={"repository": "acme/operations"},
    expected_fields={
        "title": approved_title,
        "body": content_digest(approved_body),   # compared, not stored
        "author": "acme-automation[bot]",
    },
    comparison_rules={"body": "hash"},
)

result = verify_effect(
    spec, your_reader.read_issue(number),        # None if you could not look
    proposal_id=proposal_id, execution_id=execution_id,
    toolspec_hash=assessment.toolspec.hash,
    verifier_identity="acme.github_reader/v1",
)
client.record_effect(proposal_id, result)
```

Only the fields you declared are compared. Everything else is out of
scope **by construction, not by tolerance**: a system of record has other
legitimate writers, and reporting their changes as drift would make
mismatch a noise channel operators soon learn to ignore.

`EffectStatus` keeps five outcomes apart, and the distinction that matters
most is between *we looked and it was wrong* and *we could not look*:

| Status | Terminal | Means |
|---|---|---|
| `EFFECT_VERIFIED` | yes | the declared delta is present |
| `EFFECT_MISMATCH` | yes | the object was read and differs — investigate; compensation may apply |
| `EFFECT_UNOBSERVABLE` | **no** | it could not be read in time; the effect status is unknown |
| `EFFECT_VERIFIER_FAILED` | **no** | your reader itself failed; still unknown |
| `EFFECT_UNSUPPORTED` | yes | this tool declares no postcondition — recorded so the absence is visible |

Failing to read a result is not evidence that the wrong thing happened.
Neither unknown is ever a reason to run the action again: the side effect
may already have occurred, and repeating it is the one thing this layer
must not do.

`record_effect` **appends** to the audit chain — a verifier that could
edit the record it verifies produces a claim, not evidence — and only the
hashes cross the boundary; the observed values stay with you. REMORA
stores the result as an attestation by the verifier named in the record,
not as an independent proof of its own, which is why
`verifier_identity` is mandatory. Verdicts are recorded exactly as
reported, mismatches included.

Runnable, offline, zero configuration:

```bash
python examples/effect_verification_quickstart.py
```

## Seeing repeated refusals

An ABSTAIN is terminal, which stops the call and says nothing about the
pattern. An agent refused once can adjust an argument and propose again,
and because each proposal is minted fresh, the tenth attempt looks like
the first. `AssessmentResult.lineage` makes that visible:

```python
result = client.assess(call)
if result.lineage and result.lineage.escalation_eligible:
    # Advisory. REMORA recorded the pattern; it did not route on it.
    notify_operator(result.lineage.probe_sequence_no)
```

REMORA derives this from its own audit chain, never from anything the
caller sends — a `supersedes` request field would be defeated by the one
caller it exists to catch, who omits it.

Two fields decide how much weight the verdict deserves:

- **`shadow_only`** is true while REMORA records the signal without acting
  on it. Treating eligibility as an escalation would mean acting on a
  false-positive rate nobody has measured. When it is absent from a
  response the SDK defaults it to `True`, so an omission is never read as
  "this was escalated";
- **`lineage_key_basis`** is `semantic_target` when a signed ToolSpec
  declared which argument names the target — two calls about different
  objects are then two actions, not one retried. It is `tool_only` when
  nothing declared it, and that key cannot tell repeated legitimate use
  from probing.

`lineage` is `None` on a server that does not report it. That means **not
reported**, never "no probing".

## Public surface

| Group | Symbols |
|---|---|
| Clients | `RemoraClient` (sync) and `AsyncRemoraClient` (async twin; same operations, shared error mapping so they cannot drift) — `assess`, `approve`, `reject`, `execute`, `execute_accepted`, `record_effect`, `get_proposal`, `get_lifecycle`, `export_evidence`, `verify_audit_chain`, context managers |
| Request models | `ToolCall`, `DerivationProposal` (a proposed derivation receipt for a derived argument value — verified server-side by deterministic re-execution, never by explanation) |
| Result models | `AssessmentResult`, `ApprovalResult`, `RejectionResult`, `ExecutionResult`, `AuditVerification`, `SemanticAssessment`, `AuditRef`, `ResolutionPlan`, `ProposalView`, `LifecycleTrail`, `ToolSpecIdentity` (which signed spec authorized the action, and whether specs are enforced at all) |
| Effect verification | `PostconditionSpec`, `EffectStatus`, `EffectVerificationView`, `build_postcondition`, `verify_effect`, `content_digest` |
| Proposal ancestry | `ProposalLineageView` — derived server-side; advisory while `shadow_only` is true |
| Decisions | `DecisionAction` (canonical policy enum) |
| Errors | `RemoraError` + typed subclasses (below), including the execution refusals `BindingRefusedError`, `ReplayRefusedError`, `ApprovalExpiredError` and `UnknownExecutionStateError` |

## Error taxonomy

Every error carries a stable `code`; branch on the type or the code,
never on detail strings.

| Exception | `code` | Raised on |
|---|---|---|
| `AuthenticationError` | `authentication_failed` | 401 |
| `AuthorizationError` | `authorization_denied` | 403 (e.g. role may not approve) |
| `NotFoundError` | `not_found` | 404 |
| `ConflictError` | `conflict` | 409 |
| `InvalidRequestError` | `invalid_request` | 422 |
| `RateLimitedError` | `rate_limited` | 429 (`retry_after` when the server says) |
| `ServerError` | `server_error` | 5xx (`request_id` for correlation) |
| `RemoraUnavailableError` | `unavailable` | transport failure |
| `RemoraError` | `remora_error` | base class / unmapped status |
| `BindingRefusedError` | `binding_refused` | 409 — the presented call is not the one authorized |
| `ReplayRefusedError` | `replay_refused` | 409 — the grant was already consumed (the effect may have happened) |
| `ApprovalExpiredError` | `approval_expired` | 409 — approval or token past its TTL |
| `UnknownExecutionStateError` | `unknown_execution_state` | the outcome is undeterminable; deliberately **not** retryable |

## Not part of the stable surface

- Internal modules: `remora.policy`, `remora.enforcement`,
  `remora.governance`, `remora.persistence`, `remora.execution`,
  `remora.legal`, `servers.*` — importable, no compatibility promise.
- The nested mappings on `ExecutionResult` (`execution_grant`, `pep`,
  `tool_execution`) are passed through verbatim in this SDK version;
  typed models for them are planned, additively.
- OpenAPI-generated transport, framework adapters and
  `remora.sdk.testing` are queued FT-13 slices
  (`docs/assurance/fasttrack_register_v1.yaml`).
