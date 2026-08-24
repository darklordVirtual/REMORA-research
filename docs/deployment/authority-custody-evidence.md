# Deployment evidence: the authority/execution custody split, deployed

Every value here was read from the deployed system or from a command whose
output is quoted. Nothing is inferred from configuration intent.

**Read this first.** Both mechanisms in this programme are now deployed. §7
records the exact claim that follows, and §8 records what still does not.

Superseded: earlier revisions of this document stated that the custody split was
implemented and not deployed. That was accurate when written. §3 of
`NEGATIVE_RESULTS.md` §45 records what deploying it revealed.

---

## 1. Deployment identity

| Field | Value |
|---|---|
| git commit | `6376d9411171ce11a42173559be28e72df299686` (squash-merge of #354, the deployed custody split; the durable-nonce experiments in §3-§4 ran earlier at branch commit `be4d6bbc9508`, whose tree this preserves) |
| branch | merged to `master` |
| Worker | `remora-mcp-gateway` |
| Version ID (before) | `222999e2-ef84-4fc1-8491-6d47ef4614f5` |
| Version ID (after replacement) | `9a7fc619-66f3-4074-9067-247e3286ce40` |
| Container image digest | `sha256:273228e3ced53bc1e5d619f40b3f4ef9be5c2dac050713a7bbe73459908dda25` |
| Authority container | `remora-mcp-gateway-remoracontainer` (`a03ae0d6-5abd-4ad7-bc77-7cfd8415d74e`), instance running in `rix01` |
| Execution container | `remora-mcp-gateway-remoraexecutioncontainer` (`a036dc4c-3a8e-46dd-acb8-2225932d63dd`), instance running in `otp02` |
| Worker version (split, HMAC deleted) | `6f4b1168-ac92-41c7-a734-97adca58e65b` |
| Instance type / placement | `basic`, `jurisdiction = "eu"` |
| State backend | D1 `remora-execution-state`, `running_in_region = EEUR`, served by colo `ARN` |
| Graph backend | D1 `aion-hub`, reached only via Worker binding |
| Tenant observed | `eu-pilot` |
| Access policy | app `36ee30a2…`, policy `e9980f03…`, decision `non_identity` |

### Key identity

| Key | Status |
|---|---|
| Lease signing | **Ed25519**. Private half in the AUTHORITY container only |
| `REMORA_LEASE_SIGNING_KEY` (HMAC) | **deleted from the Worker secret store**, 2026-08-24 |
| Public key | `d76d777f6219d88b44dc726f30a55ad8ac7c6cbbf6d3cee6a8297ee35b8600a8` |
| Public key fingerprint | `07801ac026e4c470` (SHA-256 of the public key, first 8 bytes) |
| `kid` | not set — single key in service |

**What this commit is and is not.** `6376d94` is the squash-merge of #354, the
commit the deployment identity above binds to. The Worker version in service
during the later experiments was built from branch work that is still unmerged
(the actor-from-lease fix and the anchored read-only allowlist, now in this PR),
so it is not reproducible from any commit on `master`. An earlier revision of
this table named that branch commit instead. That was worse in both directions:
the SHA it gave is unreachable from `master` after the branch was rebuilt, and
the parenthetical still read "squash-merge of #354", which it was not. A
deployment-evidence document that names a commit nobody can check is not
evidence.

The private key is not in this document and was not read back after generation.
Its location is asserted by configuration (`workers/mcp-gateway/src/index.ts`,
pinned by `workers/mcp-gateway/test/custody.test.ts`) and by the behavioural
result in §7.

No private key material appears in this document, and none was read. The
statement above is derived from which environment variables the Worker passes to
the container, which is a matter of source, not of secret values.

---

## 2. Outcomes recorded

Ten outcomes were requested. Six were exercised against the deployed system,
four were not, and which is which is stated rather than blurred.

| # | Outcome | Result | Evidence |
|---|---|---|---|
| 1 | Normal governed execution | **PASS** | `kg_list_predicates` under `task:survey-business-graph` → `decision: accept`, `status: executed`, `reasons: ['grounded_read_accept']` |
| 2 | Approval path | **code-level only, post-split** | `tests/test_review_path_custody_split.py`; not exercised on the deployment — see §7a |
| 3 | Exact-call mutation | **not re-run this pass** | covered by `tool_args_hash` binding tests at library level only |
| 4 | Lease replay (same process) | **PASS**, library level | `tests/test_lease_nonce_durability.py::test_a_nonce_consumes_exactly_once` |
| 5 | Replay after container replacement | **PASS, deployed** | see §3 |
| 6 | Concurrent lease spend | **PASS, deployed** | see §4 |
| 7 | Verifier-forgery attack | **FAILS ON THE DEPLOYED TOPOLOGY** | see §5 — this is a negative result, not a pass |
| 8 | Wrong ToolSpec | **not attempted** | signed-ToolSpec cloud path not implemented |
| 9 | Missing state backend | **PASS**, library level | `test_an_unavailable_store_refuses_without_burning_the_grant`; not injected on the deployed system |
| 10 | Missing signing authority | **PASS**, library level | production fail-closed now requires a lease key (NEGATIVE_RESULTS §44) |

---

## 3. Replay after container replacement — deployed

The requested experiment, run in order.

1. A governed read executed on the deployed gateway: `accept` / `executed`.
2. The lease nonce it consumed was recorded in D1:

   ```
   eu-pilot  a4d7e899-be17-436d-a2eb-235a71877d49  2026-08-23 22:26:21
   ```

   Before this change the table did not exist. Consumption had been happening
   in a `set()` inside the container.

3. The container was replaced (`wrangler deploy`; Version ID moved
   `222999e2…` → `9a7fc619…`).

4. A second governed read executed on the replacement container: `accept` /
   `executed`, consuming a *different* nonce
   `ed15e720-5097-43ba-8890-ad5b4b34efad`. The pre-replacement row was still
   present, so consumption state is external to the container by construction.

5. The nonce spent **before** the replacement was re-presented to the live
   store:

   ```
   UNIQUE constraint failed: lease_nonce_consumed.tenant_id,
   lease_nonce_consumed.nonce: SQLITE_CONSTRAINT
   (extended: SQLITE_CONSTRAINT_PRIMARYKEY) [code: 7500]
   ```

   `DurableNonceStore.try_consume` classifies this as *already consumed* and
   returns `False`; the dispatcher refuses with `nonce_already_consumed`.

**Tenant-scoped nonce namespace, same experiment.** The identical nonce string under a
different `tenant_id` was accepted (`success: true`), then deleted. Tenant A
therefore cannot spend, block, or collide with tenant B's nonce namespace.

This is a property of the nonce store and nothing more. It is **not** evidence
of tenant isolation elsewhere in REMORA -- not for the audit chain, the review
queue, the graph, or the decision path. Those need their own tests, and none
were run here.

### What this does and does not show

It shows the consumed-nonce record survives container replacement, and that
re-presenting a spent nonce is refused by the real backend. The refusal is
produced by the same SQL and the same duplicate-classification path the
dispatcher uses, and the error text above is the one `_is_duplicate()` matches —
so the classifier is confirmed against D1's actual message rather than against a
fake.

It does **not** show a full end-to-end lease replay through `/mcp`, because the
lease is internal to the container and is never exposed to an MCP caller: there
are no "same lease bytes" for an external client to re-present. The externally
reachable equivalent — re-redeeming a proposal — was already evidenced
previously as `unknown_proposal`.

---

## 4. Concurrent spend — deployed

Six simultaneous consumers of one nonce against the live EEUR database:

```
WON
REFUSED
REFUSED
REFUSED
REFUSED
REFUSED
```

Exactly one winner. Atomicity is provided by the composite primary key in D1,
not by application logic, which is why it holds across processes and containers
rather than only within one. Test rows were removed; the final table state is
two legitimate `eu-pilot` rows.

---

## 5. The forgery attack — before and after

**Before the split**, the attack succeeded, and that is recorded rather than
deleted. `tests/test_lease_authority_custody.py::test_the_deployed_symmetric_topology_permits_forgery`
still runs and still asserts that a component holding what the old deployment's
container held mints a lease for a different tool, arguments, tenant and target
— and that it verifies. It is the *before* half of the evidence and must not be
removed when it becomes historical.

**After the split**, the same forgery is refused, at issuance and at
verification, by `test_the_target_asymmetric_topology_refuses_the_same_forgery`
and `test_a_forgery_assembled_by_hand_also_fails_verification`. The second
matters independently: an attacker need not call `issue()`, so the property has
to hold where the execution path actually checks.

### What was verified against the deployment, and what was not

The library tests establish the mechanism. They cannot, by themselves, establish
that the deployed executor lacks the private key — that is a configuration fact.
Three things were done instead, and each is stated for what it is:

1. **Configuration, pinned by test.** `workers/mcp-gateway/test/custody.test.ts`
   parses the `envVars` block of each container class and asserts that
   `RemoraExecutionContainer` receives `REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC`
   and contains neither `ED25519_PRIVATE` nor `REMORA_LEASE_SIGNING_KEY`. The
   first version of that test failed on a comment documenting the property it
   was asserting; it now strips comments and tests only assignments.

2. **The symmetric key was deleted from the secret store.** Not merely
   unreferenced — `wrangler secret delete REMORA_LEASE_SIGNING_KEY`, confirmed
   absent from `wrangler secret list`. There is no HMAC lease key anywhere in
   the deployment to fall back to.

3. **Governed execution still works.** This is the load-bearing behavioural
   result. With no symmetric lease key in existence, a lease can only be signed
   with Ed25519, and only the authority container holds that private half. A
   successful `accept` / `executed` therefore proves the authority signed with
   Ed25519 and the executor verified it holding the public key alone. Had the
   executor needed to mint, `issue()` would have refused (`LeaseRefused`); had
   the authority lacked the key, there would have been no lease at all.

**What this does not prove.** No code was executed inside the deployed execution
container to attempt a mint from within it. The claim rests on the configuration
test, the deletion of the symmetric key, and the behavioural result above — not
on an in-container attack. A reviewer who wants that stronger evidence would
need a debug surface the deployment deliberately does not have.

## 6. Durability, retested after the split

Architecture movement does not preserve replay protection by assumption, so the
durable-nonce experiments were re-run against the two-domain topology.

The nonce is now consumed by the **execution** container, not the one that
decided. Rows appear under tenant `eu-pilot` after each governed call:

```
eu-pilot  974edd83-5fc4-40fc-8172-19a863e7029d  2026-08-24 06:07:59
eu-pilot  919e7894-dbdb-4b9a-b79b-abc19024892f  2026-08-24 06:06:27
```

Re-presenting the post-split nonce `974edd83…` to the live store:

```
UNIQUE constraint failed: lease_nonce_consumed.tenant_id,
lease_nonce_consumed.nonce: SQLITE_CONSTRAINT
(extended: SQLITE_CONSTRAINT_PRIMARYKEY) [code: 7500]
```

Six concurrent consumers of one nonce against the live EEUR database: **exactly
one winner**, five refused. Test rows removed afterwards.

Container replacement was demonstrated before the split (§3) and its mechanism
is unchanged — the ledger is in D1, external to both containers by construction.
It was not re-run after the split, and is therefore carried forward as evidence
for the mechanism rather than re-asserted for this topology.

**Outage: untested on the deployment.** No state-store outage was injected
against the running system. The fail-closed and does-not-burn-the-grant
properties remain library-level only
(`tests/test_lease_nonce_durability.py`).

## 7. The claim

Scoped to exactly what was demonstrated:

> For this deployment, as of Worker version
> `6f4b1168-ac92-41c7-a734-97adca58e65b`, the execution component possessed only
> public ExecutionLease verification material: no Ed25519 private key was passed
> to it and no symmetric lease key existed in the deployment. Under the recorded
> attack it could not mint new execution authority.

## 7a. The review path: tested in code, untested on the deployment

The ACCEPT path was verified against the running system (§5). The **review
path** -- VERIFY/ESCALATE, a human approves, the agent redeems -- was **not**,
because approving requires a role credential this session does not hold.

Saying "it goes through the same wrapper" is precisely the reasoning that
failed twice in §45, so it is not relied on. `tests/test_review_path_custody_split.py`
runs the whole path through the real API with only the transport stubbed: the
queue, the approval, the freshness re-gate, the one-time grant, Ed25519
issuance on the authority, and the forward. It establishes that

- an approved call crosses the boundary carrying an Ed25519 lease bound to the
  approved arguments, target, tenant and proposal identity;
- the authority does not run the tool (it holds no callables);
- an unreachable executor leaves the item unexecuted rather than reported done;
- an **unapproved** item and a **mutated** call never cross the boundary at all,
  so a refusal costs nothing on the far side.

What it does not establish is that the deployed review path works end to end.
That is an open gap with a known cause, and it is the first thing to close when
an approver credential is available.

## 8. What is NOT claimed

- **Not** that REMORA cannot be bypassed. The execution container holds the
  downstream credentials, by design — it is the component that causes effects.
  A compromise there cannot forge authority and **can** still call the
  downstream system directly. That is the ambient-bypass property (E2), it is
  untouched by splitting keys, and the source says so where someone changing it
  will read it.
- **Not** that the deployment is secure. One property was closed.
- **Not** that the executor cannot create authority under all compromise
  models. It cannot under the recorded attack, with the recorded key topology.
- **Not** controlled_pilot. The signed-ToolSpec cloud path is still not
  implemented, so the profile prerequisites do not hold and the profile is not
  set.
- **Not** that `PolicyDecisionToken` or the A2A envelope are protected. Both
  remain symmetric; their verifiers can still mint. `REMORA_PDP_SIGNING_KEY`,
  `REMORA_AUDIT_SIGNING_KEY` and `REMORA_ENVELOPE_SIGNING_KEY` are still
  supplied to both containers.
- **Not** that Postgres or SQLite durable nonce storage is deployment-proven.
  D1 is; the other two are library-level.

## 9. Reproduction

The Access service token used for these calls was created for this experiment,
added to policy `e9980f03…` alongside the existing operator token (which was
never modified and kept working throughout), and **both the policy entry and the
token were removed afterwards**. Reproducing requires a service token admitted
by that policy.

```bash
# 1. governed execution
curl -X POST https://remora-mcp-gateway.razorsharp.workers.dev/mcp \
  -H "CF-Access-Client-Id: $ID" -H "CF-Access-Client-Secret: $SECRET" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
       "name":"kg_list_predicates","arguments":{
       "graph":"urn:exeqta:tenant:luftfiber:business",
       "intent_ref":"task:survey-business-graph"}}}'

# 2. the durable record
npx wrangler d1 execute remora-execution-state --remote \
  --command "SELECT tenant_id, nonce, consumed_at FROM lease_nonce_consumed"

# 3. the replay
npx wrangler d1 execute remora-execution-state --remote \
  --command "INSERT INTO lease_nonce_consumed (tenant_id,nonce) VALUES ('eu-pilot','<spent-nonce>')"
```
