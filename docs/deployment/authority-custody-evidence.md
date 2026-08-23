# Deployment evidence: durable lease consumption, and the custody split that is not yet deployed

Every value here was read from the deployed system or from a command whose
output is quoted. Nothing is inferred from configuration intent.

**Read this first.** One of the two mechanisms in this programme is deployed and
evidenced. The other is implemented, tested, and **not deployed**. This document
separates them, and the separation is the point: the custody claim is
deliberately not made.

---

## 1. Deployment identity

| Field | Value |
|---|---|
| git commit | `1d0843d7214ea1e9eb09343b919326e69a4aad7a` |
| branch | `assurance/cloudflare-authority-custody-split` |
| Worker | `remora-mcp-gateway` |
| Version ID (before) | `222999e2-ef84-4fc1-8491-6d47ef4614f5` |
| Version ID (after replacement) | `9a7fc619-66f3-4074-9067-247e3286ce40` |
| Container image digest | `sha256:273228e3ced53bc1e5d619f40b3f4ef9be5c2dac050713a7bbe73459908dda25` |
| Container application | `remora-mcp-gateway-remoracontainer` (`a03ae0d6-5abd-4ad7-bc77-7cfd8415d74e`) |
| Instance type / placement | `basic`, `jurisdiction = "eu"` |
| State backend | D1 `remora-execution-state`, `running_in_region = EEUR`, served by colo `ARN` |
| Graph backend | D1 `aion-hub`, reached only via Worker binding |
| Tenant observed | `eu-pilot` |
| Access policy | app `36ee30a2…`, policy `e9980f03…`, decision `non_identity` |

### Key identity

| Key | Status |
|---|---|
| Lease signing | **HMAC-SHA256, symmetric**, `REMORA_LEASE_SIGNING_KEY`, supplied to the execution container (`index.ts:170`) |
| Ed25519 lease keypair | **not generated, not deployed** |
| `kid` | none — no asymmetric key is in service |
| Public key fingerprint | **none to report** |

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
| 2 | Approval path | **not re-run this pass** | previously evidenced by `deploy/gateway/demo.py`; no new evidence, so no new claim |
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

## 5. The forgery attack — the deployed topology fails it

This is the primary evidence the programme asked for, and the honest result is
a failure.

**Configuration.** The execution container is supplied
`REMORA_LEASE_SIGNING_KEY` (`index.ts:170`). `ExecutionLease` signs and verifies
under that one symmetric key.

**Attack.** Give a component exactly what the execution container legitimately
holds, then mint a lease for a different tool, different arguments, a different
tenant and a different target — none of it ever assessed by any PDP.

`tests/test_lease_authority_custody.py::test_the_deployed_symmetric_topology_permits_forgery`
runs precisely that and asserts the forged lease **verifies**.

**Result: the attack succeeds.** An adversary with code execution in the
deployed container does not need to forge anything — they hold the key, so they
author valid authority. The authorization system is bypassed rather than
attacked.

**The same attack under the target topology** —
`test_the_target_asymmetric_topology_refuses_the_same_forgery` and
`test_a_forgery_assembled_by_hand_also_fails_verification` — is refused, both at
issuance and at verification. The second matters independently: an attacker need
not call `issue()`, so the property has to hold where the execution path
actually checks.

The difference between those two tests is the entire value of the custody split,
and it is currently a difference between a deployed configuration and an
undeployed one.

---

## 6. What is deliberately not claimed

- **No separation claim.** The Ed25519 keypair has not been generated and the
  execution container has not been reduced to a public key. `docs/deployment/authority-key-topology.md`
  §2 remains a target, not a description.
- **No controlled-pilot claim.** The signed-ToolSpec cloud path is not
  implemented; `REMORA_RUNTIME_PROFILE` remains deliberately unpinned.
- **No claim that durable consumption is proven for every backend.** Postgres
  and SQLite are evidenced at library level; **D1 is evidenced on the
  deployment**, and that is the one this gateway runs.
- **No claim about `PolicyDecisionToken` or the A2A envelope.** Both remain
  symmetric; their verifiers can still mint.

---

## 7. Reproduction

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
