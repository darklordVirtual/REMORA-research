# Author: Stian Skogbrott
# License: Apache-2.0
"""A2A governance envelope — identity, delegation, and evidence for
agent-to-agent requests.

Agent-to-agent (A2A) protocols standardise *how* agents talk to each other;
they do not answer the governance questions an operator must answer before
letting an external agent act: who is this agent, who vouches for it, what
exactly was it delegated to do, under which policy version, and where does
the evidence land if something goes wrong?

This module defines a signed, auditable envelope that carries those answers
alongside any A2A request:

- **Identity and accountability** — agent id/version, issuing organisation,
  and the organisation accountable for the agent's actions. Verification
  fails closed when accountability is absent.
- **Delegation chain with capability attenuation** — an ordered chain of
  delegation links. Each link may only *narrow* the scope it received
  (subset semantics); verification rejects any link that widens scope, and
  rejects requests outside the final delegated scope. This mirrors the
  engine's decision monotonicity: authority can be reduced along a chain,
  never amplified.
- **Policy and evidence binding** — the policy version the counterparty
  evaluated, a reference to the governing decision (e.g. a DecisionEnvelope
  id or tool-call hash), and content-addressed evidence references, so a
  dispute can be replayed against the exact policy and evidence involved.
- **Integrity** — HMAC-SHA256 over a canonical serialisation, same signing
  discipline as ``remora.enforcement.token`` (PDP → PEP tokens).

Scope strings are opaque capability names (e.g. ``"workorder:read"``,
``"workorder:propose_change"``). Hierarchical wildcard matching is
deliberately NOT supported — a wildcard grant cannot be attenuated safely,
and the RBAC audit (REM-022/023) removed wildcard authority for the same
reason.

The signing key is read from ``REMORA_A2A_SIGNING_KEY``. Unsigned envelopes
can be created (development mode) but never verify as valid.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from dataclasses import replace as dataclass_replace
from datetime import datetime, timezone

PROTOCOL_VERSION = "remora-a2a-governance/v1"
_ENV_KEY = "REMORA_A2A_SIGNING_KEY"


def _get_signing_key() -> bytes | None:
    val = os.environ.get(_ENV_KEY, "").strip()
    return val.encode() if val else None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AgentIdentity:
    """Who the acting agent is, and who is accountable for it."""

    agent_id: str
    agent_version: str
    issuer_org: str          # organisation that operates / attests the agent
    responsible_org: str     # organisation accountable for the agent's actions
    attestation_ref: str | None = None  # URI or hash of an attestation artifact


@dataclass(frozen=True)
class DelegationLink:
    """One link in a delegation chain: delegator grants delegatee a scope.

    ``scope`` is the full capability set granted by this link. A valid chain
    only ever narrows: ``link[n].scope ⊆ link[n-1].scope``.
    """

    delegator: str
    delegatee: str
    scope: tuple[str, ...]
    issued_at: str
    expires_at: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    failures: tuple[str, ...]


@dataclass(frozen=True)
class A2AGovernanceEnvelope:
    """Signed governance context accompanying an agent-to-agent request."""

    envelope_id: str
    protocol: str
    identity: AgentIdentity
    delegation_chain: tuple[DelegationLink, ...]
    requested_scope: tuple[str, ...]
    policy_version: str
    decision_ref: str | None
    evidence_refs: tuple[str, ...]
    issued_at: str
    expires_at: str | None
    signature: str = ""
    is_signed: bool = False
    # Non-signed convenience metadata (display only; never trusted).
    display_name: str | None = field(default=None, compare=False)

    # ------------------------------------------------------------------
    # Canonical serialisation and signing
    # ------------------------------------------------------------------

    def _signable_payload(self) -> bytes:
        data = asdict(self)
        data.pop("signature", None)
        data.pop("is_signed", None)
        data.pop("display_name", None)
        return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()

    @classmethod
    def issue(
        cls,
        *,
        identity: AgentIdentity,
        delegation_chain: tuple[DelegationLink, ...],
        requested_scope: tuple[str, ...],
        policy_version: str,
        decision_ref: str | None = None,
        evidence_refs: tuple[str, ...] = (),
        expires_at: str | None = None,
        signing_key: bytes | None = None,
    ) -> A2AGovernanceEnvelope:
        """Create an envelope, signed when a key is available.

        ``signing_key`` overrides the ``REMORA_A2A_SIGNING_KEY`` environment
        variable (useful for tests and per-counterparty keys).
        """
        envelope = cls(
            envelope_id=str(uuid.uuid4()),
            protocol=PROTOCOL_VERSION,
            identity=identity,
            delegation_chain=delegation_chain,
            requested_scope=tuple(requested_scope),
            policy_version=policy_version,
            decision_ref=decision_ref,
            evidence_refs=tuple(evidence_refs),
            issued_at=_utcnow_iso(),
            expires_at=expires_at,
        )
        key = signing_key if signing_key is not None else _get_signing_key()
        if key is None:
            return envelope
        signature = hmac.new(key, envelope._signable_payload(), hashlib.sha256).hexdigest()
        return dataclass_replace(envelope, signature=signature, is_signed=True)

    # ------------------------------------------------------------------
    # Verification — fail closed
    # ------------------------------------------------------------------

    def verify(
        self,
        *,
        signing_key: bytes | None = None,
        now: datetime | None = None,
    ) -> VerificationResult:
        """Verify integrity, accountability, and delegation attenuation.

        Every check failure is reported (not just the first) so audit logs
        show the complete defect set. An envelope with any failure is invalid.
        """
        failures: list[str] = []

        # 1. Signature — unsigned never verifies.
        key = signing_key if signing_key is not None else _get_signing_key()
        if not self.is_signed or not self.signature:
            failures.append("unsigned_envelope")
        elif key is None:
            failures.append("no_verification_key")
        else:
            expected = hmac.new(key, self._signable_payload(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, self.signature):
                failures.append("signature_mismatch")

        # 2. Protocol pin.
        if self.protocol != PROTOCOL_VERSION:
            failures.append(f"unsupported_protocol:{self.protocol}")

        # 3. Accountability — issuer and responsible org are mandatory.
        if not self.identity.agent_id.strip():
            failures.append("missing_agent_id")
        if not self.identity.issuer_org.strip():
            failures.append("missing_issuer_org")
        if not self.identity.responsible_org.strip():
            failures.append("missing_responsible_org")

        # 4. Policy binding.
        if not self.policy_version.strip():
            failures.append("missing_policy_version")

        # 5. Delegation chain attenuation.
        failures.extend(self._verify_delegation_chain())

        # 6. Requested scope must be covered by the effective delegated scope.
        effective = self.effective_scope()
        if not self.requested_scope:
            failures.append("empty_requested_scope")
        else:
            excess = set(self.requested_scope) - effective
            if excess:
                failures.append(f"scope_exceeds_delegation:{','.join(sorted(excess))}")

        # 7. Expiry (envelope and every chain link).
        now_dt = now or datetime.now(timezone.utc)
        if self.expires_at is not None and _parse_iso(self.expires_at) <= now_dt:
            failures.append("envelope_expired")
        for i, link in enumerate(self.delegation_chain):
            if link.expires_at is not None and _parse_iso(link.expires_at) <= now_dt:
                failures.append(f"delegation_link_expired:{i}")

        return VerificationResult(valid=not failures, failures=tuple(failures))

    def _verify_delegation_chain(self) -> list[str]:
        failures: list[str] = []
        if not self.delegation_chain:
            failures.append("empty_delegation_chain")
            return failures
        previous_scope: set[str] | None = None
        previous_delegatee: str | None = None
        for i, link in enumerate(self.delegation_chain):
            if not link.scope:
                failures.append(f"empty_scope_at_link:{i}")
            if any("*" in capability for capability in link.scope):
                failures.append(f"wildcard_scope_at_link:{i}")
            if previous_scope is not None:
                widened = set(link.scope) - previous_scope
                if widened:
                    failures.append(
                        f"scope_widened_at_link:{i}:{','.join(sorted(widened))}"
                    )
                if previous_delegatee is not None and link.delegator != previous_delegatee:
                    failures.append(f"broken_chain_at_link:{i}")
            previous_scope = set(link.scope)
            previous_delegatee = link.delegatee
        final = self.delegation_chain[-1]
        if final.delegatee != self.identity.agent_id:
            failures.append("final_delegatee_is_not_acting_agent")
        return failures

    def effective_scope(self) -> set[str]:
        """The scope actually available to the acting agent: the final link's
        scope intersected with every ancestor (attenuation-safe even when the
        chain itself is invalid)."""
        if not self.delegation_chain:
            return set()
        effective = set(self.delegation_chain[0].scope)
        for link in self.delegation_chain[1:]:
            effective &= set(link.scope)
        return effective

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def from_json(cls, raw: str) -> A2AGovernanceEnvelope:
        data = json.loads(raw)
        identity = AgentIdentity(**data.pop("identity"))
        chain = tuple(
            DelegationLink(**{**link, "scope": tuple(link["scope"])})
            for link in data.pop("delegation_chain")
        )
        data["requested_scope"] = tuple(data.get("requested_scope") or ())
        data["evidence_refs"] = tuple(data.get("evidence_refs") or ())
        return cls(identity=identity, delegation_chain=chain, **data)


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
