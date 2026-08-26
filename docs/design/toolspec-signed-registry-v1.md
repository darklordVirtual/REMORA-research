# ADR: A single signed ToolSpec registry for assessment and dispatch

## Status

**ACCEPTED 2026-08-05** (REMORA to AAE handoff gate, PR 1).

All eight open questions below are now decided. The decisions are not
recorded here in prose alone; they live in `schemas/tool_spec_v1.yaml`
as a frozen, machine-readable contract, pinned by
`tests/test_toolspec_schema_v1.py`, so runtime and ADR cannot drift apart
without a test failing. Read that file for the authoritative answer to any
"Open decision" heading further down; the prose is kept because the
*reasoning* is worth preserving even where the conclusion has moved.

**Nothing is implemented yet.** The contract is frozen; runtime
enforcement is PR 2 of the handoff gate, and the SDK surface is PR 5. The
fasttrack register remains the authority on what is wired.

| Open question | Decision | Why |
|---|---|---|
| 1. Signing model | HMAC-SHA256, deployment-held key | Same trust model as PDP tokens, leases and audit entries; asymmetric/KMS deferred rather than shipped half-exercised |
| 2. Effect cardinality | Singular | `ToolContract` enforces one today; pluralising with no multi-effect tool invents an unexercised invariant |
| 3. Tool-id namespace | Flat | Namespacing touches every call site passing a bare name; uniqueness enforced at load instead |
| 4. Argument-schema failure | Hard refuse in strict mode | `schema_valid` was downgrade-only *because nothing validated it*; a computed failure that only lowers trust would let a malformed call run |
| 5. `callable_digest` basis | Source span | Human-auditable and version-stable; its blindness to closures and module globals is recorded in the contract rather than discovered later |
| 6. Pin-mode default | Strict when a bundle is configured; no TOFU | Without a bundle the legacy path runs and is **recorded as degraded**, never treated as equivalent |
| 7. `postcondition_reader` mandatory | Present but nullable in v1 | No reader exists yet (FT-04 builds the first); an explicit `null` is a decision, a missing key is an oversight |
| 8. Module home | `remora/toolcall/toolspec.py` | The assess path already imports `remora.toolcall`; enforcement receives a resolved spec as **data**, so no new import direction is created |

Additional decisions the handoff gate required beyond the original eight:
key ownership (deployment; an agent that can sign its own spec can grant
itself anything), trust-bundle distribution, key rotation and revocation
via an identity allowlist, stale-version rejection by pinned bundle
digest, and the canonical signing byte definition. All are in the frozen
contract.

This closes issue #83 (F-03) and issue #38 (same finding, discovered
independently), not by merging; by giving the maintainer a design to
accept, amend, or reject. It also narrows, and folds in, RF-01
(`docs/13-research-frontier-roadmap.md`), whose `ToolIntegrityGate`
reference sketch becomes part of ToolSpec verification rather than a
parallel mechanism.

## Context

### Already hash-bound (slices 1–2, landed)

Per the issue #83 thread: commit `14ae473` bound the API composite hash to
the canonical seven-file policy source set
(`remora/policy/versioning.py::_POLICY_SOURCE_FILES`); commit `dd4acf0`
folded tool-policy identity into the same composite. Concretely,
`servers/api.py::_tool_registry_component_hash()` (lines 708–738) hashes the
full `TOOL_REGISTRY` dict (`servers/execution_api.py` lines 91–125:
`risk_tier`, `domain`, `action_type`, optionally `target_environment` /
`rollback_available` / `schema_valid`, keyed by tool name), plus, for each of
`REMORA_TOOL_REGISTRY_MODULE` and `REMORA_SEMANTIC_BUNDLE_MODULE`, the module
spec string and a SHA-256 of the module file's full bytes (resolved via
`importlib.util.find_spec`, never imported to hash; unresolvable →
`"unresolved"`, no file-backed origin gives `"no-source"`; both are hash inputs,
not silent gaps).

That composite is signed transitively: `ExecutionLease.issue()`
(`remora/enforcement/lease.py` lines 110–169) binds `policy_bundle_hash` into
an HMAC-signed lease, and `GovernedToolDispatcher.dispatch()` refuses when
the lease's hash no longer matches the freshly recomputed composite. Two
pinned tests carry this: `test_policy_hash_covers_canonical_policy_source_set`,
`test_tool_registry_module_source_moves_the_policy_hash`. This already closes
the crudest version of F-03 ("swap the callable behind a low/read name and
the lease keeps verifying").

### What the whole-file digest cannot see

- **No per-tool granularity.** One digest covers every tool in a file.
  `deploy/ot-pilot/ot_registry.py` registers six tools from one module; the
  hash cannot name which one drifted, or distinguish a docstring edit from a
  rewired callable.
- **No description field exists to pin.** Neither `TOOL_REGISTRY` nor
  `ToolContract` (`remora/toolcall/routing/tool_contract.py` lines 36–71)
  carries free text. There is nothing to compute a `description_sha256`
  over; the exact channel MCPTox and Tool Poisoning Attacks target is
  currently unmodeled, not merely unhashed.
- **No real argument schema.** `ToolSignature.required_params`
  (`remora/toolcall/routing/tool_registry.py` line 77) is a bare name tuple;
  `schema_valid` (`TOOL_REGISTRY`, `ToolCallRequest` line 564) is an
  asserted, downgrade-only bool, never checked against an actual schema.
- No credential scope anywhere: `lease.py`'s docstring (line 14) names
  the gap: the dispatcher "holds the tool callables (and thus any
  downstream credentials they close over)," nothing declared to check it.
- **`rollback_available` is an unlinked bool** (`TOOL_REGISTRY["update_work_order"]`,
  line 123); no compensating-tool reference, no postcondition reader.
- No timeout or network policy: `GovernedToolDispatcher.dispatch()`
  calls `fn(arguments)` (line 423) synchronously, unbounded.
- **The registry itself is unsigned.** Its hash rides inside the
  HMAC-signed lease/token, protecting an *outstanding lease* from change
  underneath it; not letting an auditor verify a registry snapshot's
  provenance independent of any live lease.

### The three-way split this design collapses

One `tool_name` must independently agree across three structures: (1)
`TOOL_REGISTRY` (risk/domain/action_type, read by
`_observation_with_context()`, `servers/execution_api.py` lines 609–696);
(2) the `REMORA_TOOL_REGISTRY_MODULE` callable registry (`name -> Callable`
only, no metadata, `_tool_dispatcher()` lines 342–356); (3)
`REMORA_SEMANTIC_BUNDLE_MODULE` (`ToolSignature` + `ToolContract`, whose
`bundle_hash`/`state_hash` are always *computed*, never declared;
`SemanticBundle.__post_init__`, `remora/toolcall/semantic_bundle.py` lines
108–117, a pattern worth keeping). Today a mismatch fails toward caution in
each path individually (unknown tool → `critical`/`unknown` defaults,
`UNKNOWN` semantic fields, or `unknown_tool` refusal); the finding is not
that disagreement is silently accepted, it is that there is no single
authoritative artifact for the three to agree against.

## Decision drivers

- Close F-03 literally: one immutable, signed structure read by both assess
  and dispatch, so "what a tool name means" is one fact, not three kept in
  sync by convention.
- Anchor against a named threat model (MCPTox, arXiv:2508.14925); state
  which fields close which vectors, and which vectors stay out of scope.
- Preserve the "computed, not declared" hash discipline `SemanticBundle`
  already established.
- Do not regress the current fail-toward-caution behavior during migration.
- Keep the OT pilot (`deploy/ot-pilot/`) runnable at every slice; it is the
  only environment exercising assess, approve and execute end to end.

## Proposed ToolSpec schema

Preview of `schemas/tool_spec_v1.yaml`: one entry per tool, plus a
registry-level signature. Field-by-field rationale (what each subsumes)
follows the sketch rather than as inline comments, to keep the shape
readable.

```yaml
# schemas/tool_spec_v1.yaml (PROPOSED)
schema_version: 1
tool_specs:
  - tool_id: set_valve_position
    version: 3
    callable_digest: "sha256:9f2a..."
    implementation_identity: "ot-pilot@<git-sha>"
    description: >
      Set the position of a control valve identified by tag, as a
      percentage open. Fails if the valve tag is unknown.
    description_sha256: "sha256:1c44..."   # computed, never declared
    argument_schema:
      type: object
      properties:
        valve: {type: string}
        position_pct: {type: integer, minimum: 0, maximum: 100}
      required: [valve, position_pct]
      additionalProperties: false
    semantic_contract:
      capability: process_control
      effects: [update]
      resource_types: [valve]
      argument_roles: {valve: target_resource}
      state_delta: {valve.position: changed}
    capabilities: [process_control]
    credential_scope: [ot-plant:valve:write]
    allowed_targets: [staging, prod]
    idempotency_contract: {safe_to_retry: true, key_derivation: canonical_args}
    postcondition_reader: ot_plant.read_valve_position
    compensation_tool: null
    timeout_policy: {dispatch_timeout_seconds: 10}
    network_policy: {egress: none}
    signing_identity: ot-pilot-registry-signer-v1
registry_signature:
  signing_identity: ot-pilot-registry-signer-v1
  algorithm: HMAC-SHA256
  signed_at: "2026-08-05T00:00:00Z"
  signature: "..."   # over canonical JSON of tool_specs, sorted by tool_id
```

Field rationale, and what each subsumes:

- `tool_id`: subsumes the `TOOL_REGISTRY` key, `ToolSignature.name`,
  `ToolContract.tool`, and the dispatcher registration key: one string,
  checked for uniqueness at load, instead of trusted to agree by convention.
- `version`: new; no registry entry is versioned today. Enables the
  stale-but-validly-signed-version drift test.
- `callable_digest`: narrows `_tool_registry_component_hash()`'s
  whole-*module-file* digest to one callable (Open Decision 5: basis).
- `implementation_identity`: new; names which build bound this
  callable_digest, the literal F-03 attack surface.
- `description` / `description_sha256`: new; no free-text field exists
  in the repo today. The direct MCPTox / Tool-Poisoning-Attack anchor.
- `argument_schema`: subsumes `ToolSignature.required_params` (bare
  names) and the asserted-only `schema_valid` bool; an actual JSON Schema,
  checked, not asserted.
- `semantic_contract`: embeds `ToolContract` wholesale (already sound:
  `is_read`/`mutation` consistency, `ToolContractRegistry.get()` returns
  `None` for undeclared tools rather than inventing one). Pluralized
  `effects`/`resource_types` per the fasttrack list; see Open Decision 2.
- `capabilities`: top-level mirror of `semantic_contract.capability`
  for routing/allowlisting without descending into the contract.
- `credential_scope`: new; `lease.py` names the gap. Declare-and-audit
  only in v1 (Non-goals).
- `allowed_targets`: generalizes the single `target_environment`
  string (`TOOL_REGISTRY`, `ExecutionLease.verify()` exact-match, line 255)
  to an allowlist.
- `idempotency_contract`: subsumes the request-level `idempotency_key`
  (`ToolCallRequest`), a client-supplied cache key for `/assess` only, not a
  tool-level safety declaration. Owed per #83's F-02 interlock note.
- `postcondition_reader` / `compensation_tool`: new; replaces the
  unlinked `rollback_available: True` bool with an actual reference, or
  `null` when none exists.
- `timeout_policy` / `network_policy`: new; `dispatch()` calls
  `fn(arguments)` today with neither.
- `signing_identity`: new; names who attests to this spec set (Signing
  Model, below).

## Signing model options (no winner picked)

**Option A, env-key HMAC now.** Reuse the pattern already proven in
`lease.py` (`REMORA_LEASE_SIGNING_KEY` / `REMORA_PDP_SIGNING_KEY`,
`hmac.compare_digest`): a new `REMORA_TOOLSPEC_SIGNING_KEY` signs the
canonical JSON of `tool_specs`. Cheap, offline, stdlib-only, consistent with
the enforcement path's existing fail-closed-without-a-key behavior.
Trade-off: a shared secret means anyone with process-env access can forge a
spec set, there is no non-repudiation of *which* operator signed a given
version, and rotation invalidates every previously-signed set at once.

**Option B, KMS-backed asymmetric signing later.** A cloud KMS or local
keypair signs the set; a distributable public key verifies without granting
sign capability; non-repudiation, per-identity revocation, optional
hardware backing. Trade-off: a network or key-management dependency the
enforcement path currently avoids on principle (`lease.py` and RF-01's
`tool_integrity.py` sketch are both explicitly stdlib-only, deterministic,
offline); a KMS call on the dispatch hot path is a new latency/availability
dependency for every governed call, not only registry updates.

No default is proposed beyond "ship A first, if either ships"; see Open
Decision 1.

## Migration path

Slices 1–2 landed (Context). Proposed continuation, OT pilot runnable at
every step:

- **Slice 3, ToolSpec type, no consumers.** Immutable `ToolSpec` dataclass
  with `__post_init__`-computed `description_sha256`/`callable_digest`,
  mirroring `SemanticBundle`'s invariant. Construction and hashing tested;
  nothing reads it yet.
- **Slice 4, dual-declare, single-read.** A deployment module (OT pilot
  first) exposes both the legacy `register_tools()`/`build_semantic_bundle()`
  contract and a new `declare_tool_specs() -> list[ToolSpec]`. A load-time
  drift check logs (does not block) disagreement between the two; how
  translation bugs surface before anything depends on the new path.
- **Slice 5, assess reads ToolSpec.** `_observation_with_context()`
  sources risk/domain/action_type/semantic fields from the loaded
  `ToolSpec` when present, falling back to `TOOL_REGISTRY` +
  `SemanticBundle` when absent; same "recorded, not assumed away"
  discipline the semantic bundle already uses for its own absence.
- **Slice 6, dispatch reads ToolSpec.** `GovernedToolDispatcher.register()`
  takes `(ToolSpec, callable)` pairs; `dispatch()` verifies the presented
  callable's digest against `ToolSpec.callable_digest` on every call, not
  only at registration. `ExecutionLease` gains `tool_spec_hash`, bound the
  way `tool_contract_bundle_hash` is bound today.
- **Slice 7, fold into the policy composite, sign.** Replace
  `_tool_registry_component_hash()`'s whole-file digest with the ToolSpec
  registry's own hash; sign the registry (Option A first) and verify at
  load, independent of any live lease.
- **Slice 8, collapse legacy structures.** `TOOL_REGISTRY`, the standalone
  `SemanticBundle` module contract, and `ot_registry.py` + `ot_bundle.py`
  collapse into one `ToolSpec`-declaring module per deployment. The
  slice-4 shim is removed only after this lands.
- **Slice 9, retire the dual-read fallback** once every shipped
  deployment declares `ToolSpec` natively.

Each slice is independently revertible; `run_ot_battery.py` should pass
unchanged after every slice until slice 8 intentionally retires the modules
it reads.

## Verification plan

New drift tests (likely `tests/test_toolspec_registry.py`):

- Description rug-pull: `description` changes with no version bump:
  fail closed, not silent re-pin.
- Schema drift: `argument_schema` changes with no version bump: same.
- Callable drift: registered callable's digest no longer matches
  `callable_digest`, checked at every dispatch, not only at process start
  (closes the "cached dispatcher never re-verifies" gap in
  `_tool_dispatcher()`'s caching).
- Credential-scope drift: `credential_scope` changes with no version
  bump.
- Stale-but-validly-signed version: an older, still-correctly-signed
  spec (version N-1) is presented after N was published, refused as stale,
  not accepted because the signature checks out. Applies under either
  signing option.
- Assess-with-one-spec, dispatch-with-another: the spec at
  `/v1/execution/assess` differs from the spec at `/v1/execution/execute`
  for the same `tool_id` → refused, mirroring `policy_bundle_mismatch` in
  `ExecutionLease.verify()` (line 275).
- MCPTox-style poisoning fixtures: a small, committed, offline corpus
  of poisoned descriptions/schemas, following RF-01's own fixture-corpus
  pattern ("20 poisoned descriptions ... 0 reach the planner unflagged"),
  reused as ToolSpec load-time fixtures instead of a separate
  `ToolIntegrityGate`.

Terminology: results are *checked* or *measured* against the fixture
corpus, never called a *proof*; this is searched validation over a fixed,
offline fixture set, not a guarantee over the space of possible poisoned
descriptions.

## MCPTox threat anchoring

| Poisoning vector | ToolSpec field(s) that close it | Residual / out of scope |
|---|---|---|
| Rug-pull description update | `description_sha256` + `version` + `registry_signature` | Requires strict-mode checking on every load, not just first pin (Open Decision 6) |
| Schema/parameter tampering (widened params to exfiltrate data) | `argument_schema`, signed with the description | Only closes *declared* schema drift, not a schema wrong from the start |
| Line-jumping / name reuse | `tool_id` + `version` tuple resolves to exactly one signed spec | Cross-registry collisions across multiple deployment sources unhandled in v1 (Open Decision 3) |
| Implementation swap behind a stable low-risk name (F-03 itself) | `callable_digest` + `implementation_identity`, checked every dispatch | Slice 2's whole-file digest is a coarser version already landed |
| Credential/scope escalation | `credential_scope`, declared and auditable | Declare-and-audit only — not checked against the callable's actual closed-over credentials (Non-goals) |
| Stale spec replay | `version` + latest-version pin check | — |
| Indirect prompt injection in tool **output** (not metadata) | None — out of scope | Runtime data-flow problem (AgentDojo-style), a different design |
| MCP connect-time vs. runtime trust gap | None in v1 | No MCP server support in v1 (Non-goals) |

## Open decisions for the maintainer

1. **Signing model (A vs. B).** Trade-offs above; contract-touching;
   `signing_identity`'s meaning changes with the answer.
2. **Singular vs. plural effect/resource fields.** The fasttrack list uses
   plurals; `ToolContract.__post_init__` enforces exactly one
   `effect`/`resource_type` per tool today. Plurals model multi-effect tools
   honestly; singular keeps the existing invariant checks intact.
3. **Tool-id namespace: flat vs. namespaced.** `TOOL_REGISTRY` is one flat
   dict today; namespacing (`domain:tool_id`) reduces collision risk as
   registries grow but touches every call site passing a bare name.
4. **Argument-schema failure: hard refuse vs. downgrade-only.** Today
   `schema_valid=False` only downgrades trust (issue #34's boundary). Should
   an actual schema-validation failure hard-refuse at dispatch, now that it
   is computed rather than asserted?
5. **`callable_digest` basis: bytecode vs. source span.** Bytecode is
   stable across formatting but version-fragile and not human-auditable;
   source-span digesting is auditable but blind to closure/global-state
   attacks. Neither dominates.
6. **Registry pin-mode default: strict vs. TOFU.** RF-01's
   `ToolIntegrityGate` sketch offers both; which is default for the
   research profile vs. the OT pilot?
7. **`postcondition_reader` mandatory for mutating tools?** Every tool with
   non-empty `state_delta` mutates; is `null` acceptable in v1 given no
   reference implementation exists anywhere in the repo today?
8. **Module home: `remora/toolcall/` vs. a new `remora/enforcement/`
   location.** `ToolSpec` must be importable by the assess path (imports
   `remora.toolcall.semantic_bundle` today) and the dispatch path
   (`remora/enforcement/lease.py`, no `toolcall` import today); either
   choice risks a new import-direction dependency to check before slice 3.

## Non-goals

- No KMS integration in v1; Option A ships first, if either ships.
- No MCP server support in v1 unless trivially subsumed (a static,
  version-controlled export of an MCP tool list could populate `ToolSpec`
  entries like any other deployment module; a *live* connect-time listing is
  not fetched, verified, or trusted here; that trust gap needs its own
  design).
- No inference of ToolSpec fields from source, docstrings, or an LLM; every
  field is deployment-declared, mirroring `SemanticBundle`'s computed-hash /
  declared-content split.
- No cross-deployment or cross-tenant spec sharing.
- No runtime enforcement of `network_policy` in v1; declared and auditable
  only; dispatcher enforcement is future work.
- No automatic compensation; `compensation_tool` is a reference for a
  human or out-of-band process, not an auto-triggered rollback engine.
- No claim that this design prevents tool poisoning as a category. Per the
  threat table, output-channel injection, live MCP connect-time changes,
  and credential-scope enforcement against real secrets remain explicitly
  out of scope. This narrows a stated gap; it does not close the category.
