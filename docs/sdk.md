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
pip install "remora[sdk]"        # client only (adds httpx)
pip install "remora[api,sdk]"    # + in-process server for the offline demo
```

`remora.sdk` models and errors import without the extra; only
`RemoraClient` needs httpx.

## Stability classification

| Aspect | Guarantee |
|---|---|
| Surface | The 20 symbols in `artifacts/sdk/public_api_v1.json` — nothing else |
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

**Lifecycle coverage (honest boundary):** the SDK's `execute()` covers
the review path only (VERIFY → approve → execute). The ACCEPT token has
**no REST redemption endpoint** — it is consumed by a deployment-side
PEP (`remora.enforcement`), not by this client. A governed REST dispatch
path for direct-ACCEPT proposals is tracked as issue #36 / FT-01; until
it ships, this SDK is not a complete client for the ACCEPT lifecycle.

Runnable end-to-end version, offline, zero configuration:

```bash
python examples/sdk_quickstart.py
```

It drives the full loop — honest ABSTAIN, review-routed prod write, the
typed refusal when the agent credential tries to approve its own call,
governed execution, audit-chain verification — against the real ASGI app
in-process.

## Public surface

| Group | Symbols |
|---|---|
| Clients | `RemoraClient` (sync) and `AsyncRemoraClient` (async twin; same operations, shared error mapping so they cannot drift) — `assess`, `approve`, `execute`, `verify_audit_chain`, context managers |
| Request models | `ToolCall`, `DerivationProposal` (a proposed derivation receipt for a derived argument value — verified server-side by deterministic re-execution, never by explanation) |
| Result models | `AssessmentResult`, `ApprovalResult`, `ExecutionResult`, `AuditVerification`, `SemanticAssessment`, `AuditRef` |
| Decisions | `DecisionAction` (canonical policy enum) |
| Errors | `RemoraError` + typed subclasses (below) |

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

## Not part of the stable surface

- Internal modules: `remora.policy`, `remora.enforcement`,
  `remora.governance`, `servers.*` — importable, no compatibility promise.
- The nested mappings on `ExecutionResult` (`execution_grant`, `pep`,
  `tool_execution`) are passed through verbatim in this SDK version;
  typed models for them are planned, additively.
- OpenAPI-generated transport, framework adapters and
  `remora.sdk.testing` are queued FT-13 slices
  (`docs/assurance/fasttrack_register_v1.yaml`).
