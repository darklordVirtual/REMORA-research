> **Historical snapshot (2026-10-07): producer-owned review, not an external security certification.**
> Review tool: Claude Code (AI-assisted, directed by the maintainer).
> Reviewed revision: `272b6c56fc1d1a6a41640fe4b5e0195fcc155b51`.
> Revalidated at: `b9ade2ba40cc59f1b8849e1e14b655b491a30789` (v0.12.0).
> Independence: NOT_ESTABLISHED. The reviewer and the fixer are the same
> producer; tool output is not evidence by itself (docs/AI_USE.md).
> This file is a frozen snapshot of the review as written. Current status per
> finding: [FINDING_DISPOSITION.md](FINDING_DISPOSITION.md).

# Stage 0: review rebased onto current HEAD

## Baseline

| Item | Value |
|---|---|
| HEAD | `b9ade2ba40cc59f1b8849e1e14b655b491a30789` (merge commit of #765, tag `v0.12.0`) |
| Branch | `master` |
| git status | clean apart from the untracked `review/` directory |
| Review revision | `272b6c56fc1d1a6a41640fe4b5e0195fcc155b51` (#764) |
| Code delta since review | `remora/__init__.py` and `servers/api.py`: version strings only (0.11.0 to 0.12.0). No behavioural change. |
| Local Python | 3.13.9 (Windows 11) |
| Local deps vs lock | fastapi 0.124.4 (lock 0.141.1), pydantic 2.12.5 (2.13.5), cryptography 46.0.3 (50.0.1), pytest 9.0.2 (9.1.1), httpx 0.28.1, jsonschema 4.25.1, PyYAML 6.0.3 (all three = lock) |
| Authoritative test environment | CI on Linux, Python 3.11 to 3.14, installed from `requirements-lock.txt`. Local runs are indicative only. |

Every behavioural classification below was re-checked at HEAD by reading the code and, where marked, by a probe. Probes live outside the repository (session scratchpad `verify/`) and are not evidence by themselves; each fix PR turns them into regression tests.

## Classification

| Finding | Severity (review) | Classification at HEAD | Probe |
|---|---|---|---|
| RMR-CR-001 ToolSpec HMAC trust root | HIGH | STILL_PRESENT | yes |
| RMR-CR-002 PDP token minted and consumed together | MEDIUM | STILL_PRESENT | yes |
| RMR-CR-003 tenant from header outside dev | MEDIUM | STILL_PRESENT | yes |
| RMR-CR-004 role-only separation of duties | MEDIUM | STILL_PRESENT | yes |
| RMR-CR-005 mediation opt-in per tool | MEDIUM | STILL_PRESENT | yes |
| RMR-CR-006 configuration-conditional bindings | MEDIUM | STILL_PRESENT (partly understated) | yes |
| RMR-CR-007 audit verify without key reports intact | LOW | STILL_PRESENT (understated) | yes |
| RMR-CR-008 EFFECT_VERIFIED scope and vantage | LOW | STILL_PRESENT | code reading |
| RMR-CR-009 custody guard checks declared names | INFO | STILL_PRESENT (incomplete description) | code reading |
| RMR-CR-010 paper TEE sentence | LOW | STILL_PRESENT (.md only) | code reading |
| RMR-CR-011 no signature domain separation | LOW | STILL_PRESENT (wider than reported) | code reading |
| RMR-CR-012 concurrency test hang | LOW | STILL_PRESENT | reasoning; passes in 3.6 s on 16 cores |
| RMR-CR-013 canonicalisation across languages | LOW (speculative) | CHANGED | code reading of all workers |
| RMR-CR-014 datasets in the runtime package | INFO | STILL_PRESENT (wider than reported) | file sizes |
| RMR-CR-015 ledger failure semantics | LOW | STILL_PRESENT (wider than reported) | code reading |

## Per-finding evidence and corrections to the review

### RMR-CR-001: STILL_PRESENT
- `remora/toolcall/toolspec.py:273-283` verifies with the same HMAC key that signs; `:260-271` revocation and allowlist compare labels; `:298` pin checked only when configured.
- Key read at `remora/execution/authorization.py:46`, pin at `:50` (`or None`); `signed_surface_runtime.py:164` takes the key and no pin.
- Strict profiles (`runtime_profile.py:93-109`) require bundle and trusted identities for every role and the key only for the authority role. No profile requires the pin.
- Probe: revoke identity `v1`, re-sign as `v2` with the same key and `risk_tier="low"`: loads. With a pin set: refused `toolspec_bundle_stale`.
- Missed by the review: the 2026-10-02 fix refuses relabelling the outer `registry_signature` (`toolspec.py:285-295`). Missed gap: `REMORA_TOOLSPEC_SIGNING_KEY` is not in custody's `_SIGNING_ENVS` (`custody.py:75-79`), so an executor may hold it.

### RMR-CR-002: STILL_PRESENT
- `remora/execution/service.py:628-642` and `:1185-1195` issue the token and call `gate.check(..., consume=True)` in the same function with `REMORA_PDP_SIGNING_KEY`.
- `token.py:326` signs `REMORA_PDP_ISSUER`; `verify()` (`:362-456`) never compares it. No issuer comparison anywhere in `remora/` or `servers/`.
- Probe: token minted with issuer `attacker` verifies `ok` after resetting the issuer.
- Nuance: on the direct-ACCEPT path (`service.py:361` minted at `/assess`, redeemed at `/execute-accepted`, `execution_api.py:2274`) mint and redemption are separated in time, but not in key or process.

### RMR-CR-003: STILL_PRESENT
- `servers/api.py:2050` takes the tenant from `X-Remora-Tenant` before the env check at `:2051`, which pins only the role.
- Env semantics (probed; values lower-cased and stripped): unset, `dev`, `development` = dev (role header honoured); `prod`, `production` = production (fails closed without durable state and `REMORA_API_TOKENS`); anything else, **including the empty string**, `staging` and typos = neither: tenant from header, role pinned to `operator`.
- `review` profile requires neither `REMORA_ENV` nor `REMORA_API_TOKENS`; `controlled_pilot` requires production env (`runtime_profile.py:139-145`) and is therefore not exposed.
- Probe: `REMORA_ENV=staging`, single token, header `victim` gives `('victim', 'operator')`.
- Bound: operator capabilities only (assess, evidence, execute, rerun, read); review and approval are not reachable this way.

### RMR-CR-004: STILL_PRESENT
- `review_queue.py:360-399` checks TTL and status only; `PendingReview` (`:144-152`) has no proposer; `review_service.py:116` approves without comparison; `servers/api.py:1711` lets `admin` satisfy any `approval_role`.
- The proposer is recorded only as `actor` in the chain's `assessed` event (`service.py:288`), which `approve_item` can already read.
- Missed by the review: a no-self-approval rule exists only in the TypeScript agent-control Worker, and `tests/test_security_matrix_coverage.py:22` maps "agent cannot self-approve" to that Worker test, which can be misread as covering the Python API.

### RMR-CR-005: STILL_PRESENT
- `lease.py:1043-1044` `register(..., mediated=False)`; `:1105` no mediator for unmediated tools; `:1115-1117` downstream declaration consulted only for mediated tools.
- Production registration (`servers/execution_api.py:1236`) uses a two-argument callback, so every production tool is unmediated. No production path passes `mediated=True`.
- Missed by the review: strict profiles refuse tool callables in the authority domain (`lease.py:1053`), a custody guard rather than a mediation requirement.

### RMR-CR-006: STILL_PRESENT, partly understated
Binding matrix at HEAD (in-process dispatcher):

| Binding | Compared at | When absent |
|---|---|---|
| actor | `lease.py:532-538` | skipped if the lease's `actor_identity` is empty, in every profile (production sets it) |
| toolspec_hash | `lease.py:545-549` | skipped without a bundle; strict profiles require the bundle |
| task | `lease.py:590-595` | event `dispatch.task_unchecked`; `REMORA_REQUIRE_TASK_IDENTITY` not a strict prerequisite |
| capability digest | `lease.py:949-954` | allowed; `REMORA_REQUIRE_CAPABILITY_SET` not a strict prerequisite |
| runtime identity | `lease.py:1180-1194` | strict refuses `runtime_identity_undeclared`; otherwise event |
| resolved effect | `lease.py:835-861` | **unchecked even under strict when no resolver is bound, including when the lease signs the hash** (probe: executed) |
| surface | `lease.py:981-999` | **inert on the API path**: `servers/` never binds a surface observer and production leases carry no `surface_digest` |
| plan | `lease.py:1006-1018` | fail-closed when the lease binds a plan |
| audience | `gate.py:381` | production gate always has an audience; non-issue in production |

`EnforcementGate.enforce()` (`gate.py:562-581`) has no production caller (tests and docstrings only) but is a public export.

### RMR-CR-007: STILL_PRESENT, understated
At least nine chain implementations. `TenantAuditChain.verify` without a key returns intact for a re-chained history with signatures stripped (probe); with the key it reports `signature_missing_at`. API-visible: `GET /v1/execution/audit/verify` (no signature status field) and `GET /v1/audit/chain/verify` (linkage only, no hash recomputation). No profile requires `REMORA_AUDIT_SIGNING_KEY`.

### RMR-CR-008: STILL_PRESENT
No vantage or scope on `EffectVerificationRequest`, `EffectVerification` or the response. Missed by the review: `remora/evidence/admission/models.py:203` already defines `ObservationVantage`, unwired.

### RMR-CR-009: STILL_PRESENT, description incomplete
The guard checks declared env names plus three signing variables, and is a no-op outside strict profiles. Missed by the review: role-based refusals independent of names (`custody.py:212-276`); the role itself is self-declared. Already disclosed in README and the CAP caveat.

### RMR-CR-010: STILL_PRESENT (.md only)
`paper/remora_paper.md:1491` still says "produced by the correct model under the correct policy". The `.tex` (`:2511-2514`) already uses measurement language, so md and tex diverge. Phrase also in `scripts/legacy/patch_tee_paper.py`.

### RMR-CR-011: STILL_PRESENT, wider than reported
Only `audit/checkpoint.py` uses a domain-tagged preimage (`remora-ckpt-v1|`). Untagged multi-use keys: lease HMAC falls back to `REMORA_PDP_SIGNING_KEY` (`lease_signing.py:148-150`); `REMORA_ENVELOPE_SIGNING_KEY` signs envelope hashes and Merkle roots; the Worker `ENVELOPE_SIGNING_KEY` signs envelope entries and approval records. Token and lease payloads remain field-disjoint, so no concrete forgery today.

### RMR-CR-012: STILL_PRESENT
`tests/test_concurrency_rem036.py:125-133`: a writer timeout skips `stop.set()`, and `shutdown(wait=True)` waits forever on readers. `pytest-timeout` not installed or configured; in CI the hang ends at the job's 15-minute timeout without diagnosis.

### RMR-CR-013: CHANGED
- Python binding: `canonical_tool_call_hash` (`observation.py:41-103`) with a strict JSON-domain check; `interop/jcs.py` is not on the binding path.
- mcp-gateway and agent-control re-serialise and can lose precision (integers above 2^53, `1.0` to `1`) **before** binding: the value Python binds is the value Python executes. The post-binding divergence the review hypothesised does not occur.
- agent-control's local approval path hashes insertion-ordered `JSON.stringify` and compares only against itself (fails closed on reorder). The comment at `envelope.ts:70-76` describes a comparator that does not exist.
- Golden vectors for envelope canonical JSON already exist (`tests/golden/canonical_json_vectors_v1.json`).
- Residual: pre-binding precision loss in the Workers, and downstream Python adapters re-serialising after the rehash. A v2 over RFC 8785 is not justified by this evidence; input validation for unsafe numerics at the Worker edge is the proportionate change.

### RMR-CR-014: STILL_PRESENT, wider than reported
`remora/benchmarks` is 4.1 MB in the wheel (`sap_v3_n1200.py` 963 KB, `extended_v2_n500.py` 376 KB, `extended_v2.py` 175 KB). `remora/scoring.py:7` imports `benchmarks.loaders` at runtime.

### RMR-CR-015: STILL_PRESENT, wider than reported
Postgres and SQLite (`gate.py:452-492`) catch only `IntegrityError`; `OperationalError` propagates, skipping both the `grant.checked` event and the `execution_grant_refused` chain entry. D1 maps `D1Unavailable` but not socket timeouts or JSON decode errors (`d1_connection.py:59-65`), and classifies "UNIQUE" by substring. Only D1 has an outage test.

## Consequences for the implementation order
- The requested order stands. CR-013 moves from "investigate, maybe v2" to "edge input validation plus documentation of the pre-binding conversion"; no v2 canonicalisation.
- CR-006 gains two concrete code gaps beyond documentation: resolved-effect binding unchecked under strict without a resolver, and the surface binding inert on the API path.
- CR-007 gains the linkage-only `GET /v1/audit/chain/verify`.
- Stop conditions to watch: CR-001 (ToolSpec signing format), CR-011 (signature preimages of leases and tokens) and CR-007/CR-008 (persisted evidence meaning) each touch signed or persisted artifacts and require a frozen-v1/new-v2 plan before code.
