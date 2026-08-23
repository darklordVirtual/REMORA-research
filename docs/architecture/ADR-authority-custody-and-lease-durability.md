# ADR: authority custody, lease durability, and three deferred properties

Status: A and B **accepted and implemented**. C, D and E **accepted as
direction, not implemented** — recorded so that the reasoning is reviewable
before any code is written against them.

Context: `docs/research/adjacent-systems-crosswalk-v2.md`, which corrects the
first crosswalk against HEAD. Read §1.6 and §1.4 before ADR-A and ADR-D.

Common constraint on all five: one property, one mechanism, one adversarial
test, one evidence artifact. An ADR that needs a broad refactor to land is an
ADR that is not ready.

---

## ADR-A — Asymmetric PDP→PEP authority

**Property protected.** C (Exact-Call Integrity) and B (Authority Provenance),
at the level of *who may author authority at all*.

**Threat model.** The adversary has compromised the execution container: they
can read its environment, run code in it, and call the dispatcher. The question
is whether they can only *replay* existing authority, or can *mint* new
authority for actions never assessed.

**Current state.** They can mint. `workers/mcp-gateway/src/index.ts:76-77`
supplies `REMORA_PDP_SIGNING_KEY` and `REMORA_LEASE_SIGNING_KEY` to the
container as Worker secrets. `ExecutionLease._signature()`
(`remora/enforcement/lease.py:234`) is `hmac.new(key, payload, sha256)`, and
`verify()` recomputes it with the same key. The component that enforces the
decision holds the material that authors it. The PDP→PEP boundary exists in the
architecture diagram and not in the cryptography.

This is a topology defect before it is an algorithm defect. Converting HMAC to
Ed25519 while shipping the private key to the same container would change the
algorithm and preserve the vulnerability exactly.

**Proposed state.**

- `ExecutionLease` gains an Ed25519 signature path alongside HMAC, selected by
  a `sig_alg` field carried in the signed payload (so the algorithm cannot be
  stripped or downgraded without invalidating the signature).
- Issuance requires a private key. Verification requires only a public key.
- Key material is resolved separately for the two roles:
  `REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE` (issuer) and
  `REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC` (verifier). A component holding only
  the public key can verify every lease it will ever see and can issue none.
- `kid` on the lease, so rotation and multi-key verification are possible
  without a flag day.

**Format decision: raw Ed25519 over a canonical payload, not JWS.** The
crosswalk defaulted to JWS. Rejected here on evidence: the lease is not
externally carried — it moves PDP→PEP inside one deployment, and `verify()`
already re-derives a canonical payload from typed fields, which is stronger
than parsing a self-describing token. JWS would add a parser, a header the
attacker partly controls, and the `alg` confusion class, to buy interoperability
nothing currently needs. Revisit if a lease ever crosses an organisational
boundary. COSE is explicitly not built: no constrained transport requires it.

**Alternatives considered.**

1. *Ed25519 everywhere, all six MAC sites at once.* Rejected. `merkle.py`,
   `anchor.py` and `toolspec.py` sign objects with different trust topologies —
   audit integrity and registry authenticity are not the PDP→PEP boundary, and
   converting them in one change would produce an unreviewable diff for a
   weaker reason. Signing topology table below records them as separate work.
2. *Keep HMAC, move the PDP into the Worker.* Would also fix custody, and is a
   larger deployment change with no cryptographic guarantee behind it — a
   future configuration mistake reintroduces the hole silently. Asymmetric keys
   make the property structural.
3. *Do nothing until the full migration is designed.* Rejected: dual
   verification is additive and can land now.

**Signing topology.** What this ADR changes, and what it deliberately does not.

| Object | Issuer | Now | Verifier | Verifier may mint? | Target | This ADR |
|---|---|---|---|---|---|---|
| `ExecutionLease` | PDP | HMAC-SHA256 | PEP / dispatcher | **must not** | Ed25519 | **yes** |
| `PolicyDecisionToken` | PDP | HMAC-SHA256 | `EnforcementGate` | must not | Ed25519 | no — next slice |
| A2A envelope + links | delegating agent | HMAC-SHA256 | counterparty | must not | Ed25519 | no |
| Checkpoint signature | audit writer | HMAC-SHA256 | auditor | must not | Ed25519 | no — pairs with ADR-E |
| ToolSpec registry sig | deployment | HMAC-SHA256 | runtime | must not | Ed25519 | no |
| Local integrity digests | — | SHA-256 | — | n/a | unchanged | no |

Recording the others without converting them is the point: an unconverted row
with a stated target is honest, an unrecorded one is a surprise.

**TCB change.** Reduced. The execution container moves from *holds material
that authors authority* to *holds material that verifies it*, once the
deployment supplies only the public key. The ADR does not by itself change the
deployment; it makes the smaller custody possible and testable.

**Failure modes.**

- *Downgrade.* An adversary presents an HMAC lease during the dual-accept
  window. Mitigated by making `sig_alg` part of the signed payload and by
  requiring an explicit opt-in to accept HMAC once migration completes.
  Adversarial test required.
- *Key confusion.* A public key configured where a private key is expected.
  Fails closed at issue time with a named error, not at verify time.
- *Missing dependency.* `cryptography` is an optional extra (`pyproject.toml:49`),
  so the Ed25519 path must fail closed with a clear message rather than
  silently falling back to HMAC. Silent fallback would be the whole
  vulnerability, reintroduced as a convenience.

**Migration.** Three phases, each independently shippable.
1. Verifiers accept both. Issuers still HMAC. *(this change)*
2. Issuers switch to Ed25519; HMAC leases drain within their expiry window.
3. Verifiers refuse HMAC, gated on the downgrade test. Treat the HMAC secret as
   compromised from the moment phase 2 completes and rotate it out.

**Claim boundary.** What may be claimed after this change: *the lease signature
scheme supports a custody split in which the verifier cannot mint, demonstrated
by an adversarial test at library level.* What may **not** be claimed: that the
deployed Cloudflare container no longer holds minting material. That is a
deployment change, and until it ships the claim is about the mechanism only.

---

## ADR-B — Durable `ExecutionLease` nonce consumption

**Property protected.** C (Exact-Call Integrity), specifically the single-use
half.

**Threat model.** An adversary captures a valid, unexpired lease — from a log,
a crashed process, or a proxy — and re-presents it. Also: the deployment runs
more than one dispatcher, or a container is replaced mid-window, with no
adversary at all.

**Current state.** `NonceLedger` (`remora/enforcement/lease.py:387-398`) is
`threading.Lock` plus a `set`. Its own docstring is accurate and unusually
candid: *"a lease is single-use per process, not globally: with several
workers, or after a restart, the same lease can be dispatched again"*, and
notes the contrast with `EnforcementGate`'s durable jti ledger. REM-025.

On the Cloudflare deployment this is live: containers are ephemeral by design
and are replaced on idle. The one-time property of a lease currently has the
lifetime of a container.

This is the same defect class as #350 — the guard admitted a durable backend
the gate never learned to use — one layer up. That it recurred in a second
component argues for a shared, narrow interface rather than a second bespoke
ledger.

**Proposed state.** A `NonceStore` protocol with exactly one required method:

```
try_consume(nonce, *, tenant_id) -> bool
```

Atomic (exactly one caller gets `True`), durable (a restart does not restore
authority), tenant-scoped (tenant A's namespace cannot collide with tenant B's),
and fail-closed (`NonceStoreUnavailable` — unreachable never means unused).
Backends reuse REMORA's existing durable state: Postgres, SQLite, and the D1
state endpoint the Cloudflare path already uses for `pep_consumed`.

`NonceLedger` remains the default and keeps its honest docstring, so library
and research use are unaffected.

**Alternatives considered.**

1. *Reuse `EnforcementGate`'s jti ledger directly.* Rejected: the gate consumes
   a different object at a different point, and coupling them would mean a
   lease and its token could not be independently reasoned about.
2. *A general durable key-value abstraction.* Rejected explicitly — the brief
   is right that this becomes a database layer. One method, one semantic.
3. *Make the durable store mandatory.* Rejected for now: it would break library
   and research use. The durability *guard* already refuses ephemeral state on
   the production path; that is where compulsion belongs.

**TCB change.** Neutral in size, stronger in property. The store joins the TCB;
the in-process set it replaces was already in it and was weaker.

**Failure modes.** Store unavailable → refuse, and critically *do not burn the
nonce*, so a transient outage does not permanently destroy a valid
authorization. This is the behaviour already pinned for the jti ledger
(`tests/test_gate_d1_ledger.py`) and it must hold identically here.

**Claim boundary.** Claimable: lease nonces consume exactly once across process
restart and across independent dispatcher instances *when a durable backend is
configured*, with adversarial evidence. Not claimable: that the deployed
gateway is so configured — that is a separate deployment fact requiring its own
evidence.

---

## ADR-C — Persistent trajectory provenance *(accepted as direction; not implemented)*

**Property protected.** D (Semantic Authority), extended across calls.

**Current state.** Call-level provenance exists and works
(crosswalk v2 §1.1). Two things do not: the label does not persist across
calls, and `Observation.from_record()` takes it from the caller.

**Proposed state.** A `TrajectoryProvenanceState` in tenant-authoritative
storage — the Durable Object on the Cloudflare path — carrying monotonic source
sets and authority-relevant transitions, **not** a scalar risk score. The
existing `argument_tainted` / `untrusted_controlled_arguments` fields become
*derived* from that state rather than supplied alongside it. No second taint
subsystem.

**Why not now.** The gating question is not implementability, it is whether
persistent provenance detects harmful multi-step trajectories that per-call
semantic authority misses *without collapsing legitimate autonomy*. That
requires matched trajectories — same calls, different order and provenance, one
benign and one harmful — and that corpus does not exist. Building the mechanism
first would produce a capability with no way to know whether it helps.

**Non-claim, to be published with any implementation.** *Source-granular
provenance is a conservative over-approximation and does not prove which
individual bytes influenced a particular argument.* Copied in spirit from
Janus, which states its own limitation in its source.

---

## ADR-D — External runtime/tool drift identity *(accepted as direction; not implemented)*

**Property protected.** F2, and candidate H (crosswalk v2 §3).

**Current state.** F1 is well covered — nine bound and signed fields
(crosswalk v2 §1.4). No field names the runtime that executes.

**Proposed state.** Structured components — MCP server identity, server
manifest digest, tool schema digest, adapter digest, container image digest,
Worker version, deployment generation — with an optional canonical digest over
them, bound into the lease and re-checked at the PEP immediately before
dispatch. Structured rather than one opaque hash, so a mismatch is
diagnosable: "which component drifted" is the question an operator will ask.

**Why not now.** Two blockers. The lease already carries fourteen bound fields,
and adding a fifteenth whose components cannot yet be *measured* on the
deployed path would bind a value that is either constant or absent — which
looks like coverage and is not. And the discriminating test for H needs this
mechanism to exist before H can be admitted, so implementing it inside the same
change that proposes the vocabulary would prejudge the review.

Sequence: measure the components on the Cloudflare path first; bind second;
propose H third.

---

## ADR-E — External audit anchoring *(accepted as direction; not implemented)*

**Property protected.** A (Receipt Integrity), against the operator.

**Current state.** Merkle checkpoints, chain-linked, signed, with tenant
adapters — all present (crosswalk v2 §1.3). The absence of external publication
is already recorded honestly in
`docs/enterprise/audit-anchoring-guide.md` and REM-025.

**Proposed state.** A `CheckpointPublisher` protocol, a `CheckpointReceipt`,
and a verifier that checks a chain against externally held roots. Do not touch
`remora/audit/merkle.py` or `checkpoint.py`.

**The property that decides the design.** *An attacker with complete write
access to REMORA's primary audit database cannot rewrite history older than an
externally published checkpoint without detection.* This makes the anchor's
required characteristics — independent, append-only or WORM, timestamped,
retrievable, machine-verifiable, tenant-aware — and it forbids the obvious
shortcut: **if the anchor is writable by the principal that can rewrite the
audit database, no tamper-resistance claim may be made.** An anchor in the same
cloud account under the same credentials is a diagram, not a control.

**Why not now.** The choice of destination is a deployment and commercial
decision with a real trust question attached, and picking one to have picked
one would be the exact error §5 of the crosswalk describes. The adversarial
test, however, is already specifiable and should be written before the
publisher: create entries, checkpoint, anchor, rewrite with full DB privileges,
re-link every internal hash, verify against the anchor, expect detection.

---

## What this ADR set deliberately does not propose

General MCP gateway functionality; generic IAM; LLM-based final authorization;
trust scores; any aggregate score; a new policy language; a duplicate taint
subsystem; a duplicate Merkle implementation; COSE; and multi-agent complexity
justified by ADCS's existence rather than by a delegation requirement REMORA
has.
