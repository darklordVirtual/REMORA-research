# Signing topology of the Cloudflare deployment: current and target

Read from `workers/mcp-gateway/src/index.ts` and `wrangler.toml` at commit
`ceb979f`, not from architecture prose. Every CURRENT row below is a line of
configuration, cited.

**Nothing in this document is a separation claim.** It records what the
deployment does today and what it must do instead. The claim may only be made
after the TARGET topology is deployed and the forgery attack in
`docs/deployment/authority-custody-evidence.md` has been run against it.

---

## 1. Current topology

The deployment has **one** container class, `RemoraContainer`
(`wrangler.toml`, `[[containers]]`, `max_instances = 1`). It serves
`REMORA_ENABLED_SURFACES=execution`, which is the surface that holds *both* the
policy decision point and the policy enforcement point.

| Secret | Reaches the execution container? | Line |
|---|---|---|
| `REMORA_PDP_SIGNING_KEY` | **yes** | `index.ts:169` |
| `REMORA_LEASE_SIGNING_KEY` | **yes** | `index.ts:170` |
| `REMORA_AUDIT_SIGNING_KEY` | **yes** | `index.ts:171` |
| `REMORA_ENVELOPE_SIGNING_KEY` | **yes** | `index.ts:172` |
| `REMORA_TOOLSPEC_SIGNING_KEY` | **yes**, when a bundle is configured | `index.ts:176` |
| `REMORA_GITHUB_TOKEN` | yes | `index.ts:211` |
| `REMORA_PG_DSN` | yes, when set | `index.ts:157` |
| `REMORA_API_TOKENS`, `REMORA_AGENT_TOKEN` | yes | `index.ts:167-168` |
| exeQta graph credentials | **no** — reached through the `GRAPH_DB` Worker binding via `outboundByHost` | `wrangler.toml` |

Five signing keys, all symmetric, all in the component that executes.

### Why the boundary is nominal rather than weak

The PDP→PEP boundary is not merely sharing a key by oversight. The two sides are
consecutive statements in one function. `remora/execution/dispatch.py:53-79`:

```
lease = ExecutionLease.issue(...)     # the PDP mints
...
dres = dispatcher.dispatch(lease, ...) # the PEP verifies
```

The lease is created and consumed microseconds apart, in one process, and never
crosses a boundary. There is therefore no transport to protect and no impersonation
to prevent — which is exactly why one key served both roles without anyone
noticing it was serving two roles.

**Consequence.** An adversary with code execution in the container does not need
to forge anything. They hold `REMORA_LEASE_SIGNING_KEY`, so they can mint a
valid ACCEPT lease for any tool, any arguments, any tenant and any target, and
present it to the dispatcher that holds the downstream credentials. The
authorization system is bypassed rather than attacked.

### What is genuinely already protected

Narrowly, and worth keeping separate from the above: the exeQta graph is reached
over `outboundByHost` into a Worker binding. A binding cannot be read out of a
process and replayed elsewhere, so **that one credential** does not exist in the
container to be stolen. This covers one state path. It is not a statement about
the container.

---

## 2. Target topology

The requirement: **the ExecutionLease private key exists only in the authority
issuer.** The execution component receives the public verification key and the
downstream credentials it genuinely needs, and nothing that can author
authority.

| Secret | Authority issuer | Execution container |
|---|---|---|
| `REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE` | **yes — only here** | **no** |
| `REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC` | yes | yes |
| `REMORA_LEASE_SIGNING_KEY` (HMAC) | migration window only | **no** |
| `REMORA_PDP_SIGNING_KEY` | yes | not required by the dispatcher; removal tracked separately |
| `REMORA_AUDIT_SIGNING_KEY` | yes | see §4 |
| `REMORA_ENVELOPE_SIGNING_KEY` | yes | see §4 |
| `REMORA_TOOLSPEC_SIGNING_KEY` | **neither** — signing is a build-time act; the runtime needs only trusted identities | |
| `REMORA_GITHUB_TOKEN` and downstream credentials | **no** | yes — only the dispatcher needs them |
| `REMORA_STATE_ENDPOINT` | yes | yes — the nonce ledger lives here |

Note the inversion this produces, and it is the point: the authority issuer can
create authority and cannot execute; the execution container can execute and
cannot create authority. Neither component alone is sufficient.

---

## 3. Must policy evaluation and signing be co-located?

**Yes, and this determines where the split goes.**

The constraint is that the signer must never sign an ACCEPT lease it was merely
handed. If the signer accepts caller-supplied lease fields, the split is
cosmetic: the execution container simply asks for the lease it wants and gets
it, and the private key protects nothing.

So the signer must reach the decision itself. Three placements were considered:

1. **Signer in a Worker or Durable Object, PDP in the container.** Rejected.
   The PDP is the Python decision engine with the semantic bundle, tool
   metadata and intent source; it cannot run in a Worker. A Worker-side signer
   could only sign what the container told it, which is the forbidden shape.
   A variant — the signer validates against a proposal record it already holds
   — fails for the same reason: the container also produces the decisions that
   create proposals, so it can manufacture the record it will later be checked
   against.
2. **Signer and PDP together in the execution container.** This is today.
   Rejected: it is the defect.
3. **Signer and PDP together in a separate authority container.** Accepted.
   The only placement where the signer independently reaches the decision and
   the executing component cannot influence it.

The split line is therefore **[PDP + signer] | [PEP + dispatcher]**, not
[PDP | signer + PEP].

### The orchestration that follows

The Worker routes; it never signs.

```
authenticated request (Cloudflare Access)
        │
        ▼
   thin Worker  ── identity + tenant resolution
        │
        ├──1──►  AUTHORITY CONTAINER
        │          REMORA PDP: full decision
        │          holds Ed25519 PRIVATE key
        │          holds NO downstream credentials
        │          returns a signed exact-call lease, ACCEPT only
        │
        └──2──►  EXECUTION CONTAINER   (lease from step 1)
                   holds PUBLIC key only
                   PEP verification of the full binding
                   durable tenant-scoped nonce consumption
                   GovernedToolDispatcher — holds downstream credentials
```

The execution container is not the caller of the authority endpoint. It receives
a lease it cannot have influenced beyond the call it asked to make, and which
the authority container will only issue if its own PDP reached ACCEPT for
exactly that call.

---

## 4. Deliberately out of scope here

Only the **lease** authority is converted. Recorded so the remaining rows are
visible rather than implied:

- `PolicyDecisionToken` remains HMAC. Its verifier can still mint. The gate is
  a separate object with a separate migration.
- The audit and envelope signing keys stay symmetric. Their threat model is
  tamper-evidence against an operator, which asymmetric signing alone does not
  solve — that is external anchoring (ADR-E), not a key swap.
- `REMORA_TOOLSPEC_SIGNING_KEY` should not be in either runtime component;
  signing a ToolSpec is a build-time act. Tracked with the signed-ToolSpec
  cloud path.

Each is a real remaining exposure. None is claimed fixed by this work.
