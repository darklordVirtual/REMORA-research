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
  discipline as ``remora.enforcement.token`` (PDP → PEP tokens). Each
  delegation link additionally carries its own signature and key id
  (``kid``), verified against a caller-supplied key registry, so the
  envelope issuer cannot fabricate the delegation history when link
  verification is enabled.
- **Replay and binding protection** — a mandatory ``audience`` (intended
  verifier), a per-envelope ``nonce`` checked against a caller-supplied
  replay guard, and an optional ``tool_call_hash`` binding the envelope to
  the exact action arguments (same canonical hash the enforcement gate
  recomputes before execution).

Scope strings are opaque capability names (e.g. ``"workorder:read"``,
``"workorder:propose_change"``). Hierarchical wildcard matching is
deliberately NOT supported — a wildcard grant cannot be attenuated safely,
and the RBAC audit (REM-022/023) removed wildcard authority for the same
reason.

Trust-model scope (stated plainly)
----------------------------------
This reference implementation uses symmetric HMAC keys: envelope-level with
``REMORA_A2A_SIGNING_KEY`` (or an explicit per-counterparty key), link-level
via a ``kid`` → key registry. That demonstrates the *structure* of the trust
chain — per-link attestation, attenuation, revocation-by-registry — but a
symmetric key shared between issuer and verifier proves integrity, not
third-party origin. A production deployment should replace the HMAC layer
with asymmetric signatures (JWS with key ids, published verification keys,
and rotation, as A2A-style agent-card specifications define) without
changing the envelope's field contract or verification semantics. Unsigned
envelopes can be created (development mode) but never verify as valid.
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
from typing import Callable

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

    ``kid`` names the delegator's signing key in the verifier's key registry;
    ``signature`` is HMAC-SHA256 over the link's canonical payload (everything
    except the signature itself). Sign with :func:`sign_delegation_link`.
    When the verifier supplies a key registry, every link must carry a valid
    signature from a registered key — the envelope issuer alone cannot
    fabricate the delegation history.
    """

    delegator: str
    delegatee: str
    scope: tuple[str, ...]
    issued_at: str
    expires_at: str | None = None
    kid: str | None = None
    signature: str = ""

    def signable_payload(self) -> bytes:
        data = asdict(self)
        data.pop("signature", None)
        return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()


def sign_delegation_link(link: DelegationLink, *, key: bytes, kid: str) -> DelegationLink:
    """Return a copy of *link* signed by the delegator's key (named *kid*)."""
    stamped = dataclass_replace(link, kid=kid, signature="")
    signature = hmac.new(key, stamped.signable_payload(), hashlib.sha256).hexdigest()
    return dataclass_replace(stamped, signature=signature)


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
    # Intended verifier — a receiving control plane must check this names it.
    audience: str = ""
    # Per-envelope nonce for replay protection (checked via replay_guard).
    nonce: str = ""
    # Canonical hash of the exact tool call this envelope authorises
    # (remora.policy.observation.canonical_tool_call_hash). Binds delegation
    # to arguments: the same envelope cannot authorise a different payload.
    tool_call_hash: str | None = None
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
        audience: str,
        decision_ref: str | None = None,
        evidence_refs: tuple[str, ...] = (),
        tool_call_hash: str | None = None,
        expires_at: str | None = None,
        signing_key: bytes | None = None,
    ) -> A2AGovernanceEnvelope:
        """Create an envelope, signed when a key is available.

        ``signing_key`` overrides the ``REMORA_A2A_SIGNING_KEY`` environment
        variable (useful for tests and per-counterparty keys).
        ``audience`` names the intended verifier and is mandatory.
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
            audience=audience,
            nonce=str(uuid.uuid4()),
            tool_call_hash=tool_call_hash,
        )
        key = signing_key if signing_key is not None else _get_signing_key()
        if key is None:
            return envelope
        signature = hmac.new(key, envelope._signable_payload(), hashlib.sha256).hexdigest()
        return dataclass_replace(envelope, signature=signature, is_signed=True)

    # ------------------------------------------------------------------
    # Verification — fail closed
    # ------------------------------------------------------------------

    # Tolerated clock skew when rejecting envelopes issued "in the future".
    CLOCK_SKEW_SECONDS = 300

    def verify(
        self,
        *,
        signing_key: bytes | None = None,
        now: datetime | None = None,
        expected_audience: str | None = None,
        expected_tool_call_hash: str | None = None,
        link_keys: dict[str, bytes] | None = None,
        replay_guard: "Callable[[str], bool] | None" = None,
    ) -> VerificationResult:
        """Verify integrity, accountability, and delegation attenuation.

        Every check failure is reported (not just the first) so audit logs
        show the complete defect set. An envelope with any failure is invalid.

        Parameters
        ----------
        expected_audience:
            The verifier's own identity. When given, the envelope's
            ``audience`` must match exactly. Audience must be non-empty
            regardless (an envelope addressed to no one verifies invalid).
        expected_tool_call_hash:
            Canonical hash of the tool call actually being authorised. When
            given, the envelope must be bound to exactly that hash.
        link_keys:
            ``kid`` → key registry for per-link signature verification. When
            given, every delegation link must carry a valid signature from a
            registered key — removing a key from the registry revokes every
            chain that depends on it. When omitted, link signatures are not
            checked (envelope-level integrity only) — pass a registry in any
            cross-organisation deployment.
        replay_guard:
            Callable returning True if this nonce has been seen before.
            The caller owns nonce persistence (REMORA is stateless).
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

        # 5. Audience — envelope must name its verifier, and match it.
        if not self.audience.strip():
            failures.append("missing_audience")
        elif expected_audience is not None and self.audience != expected_audience:
            failures.append("audience_mismatch")

        # 6. Replay protection.
        if not self.nonce.strip():
            failures.append("missing_nonce")
        elif replay_guard is not None and replay_guard(self.nonce):
            failures.append("replay_detected")

        # 7. Argument binding — the envelope authorises exactly one payload.
        if expected_tool_call_hash is not None:
            if self.tool_call_hash is None:
                failures.append("missing_tool_call_binding")
            elif not hmac.compare_digest(self.tool_call_hash, expected_tool_call_hash):
                failures.append("tool_call_binding_mismatch")

        # 8. Delegation chain attenuation (+ per-link signatures if registry given).
        failures.extend(self._verify_delegation_chain(link_keys))

        # 9. Requested scope must be covered by the effective delegated scope.
        effective = self.effective_scope()
        if not self.requested_scope:
            failures.append("empty_requested_scope")
        else:
            excess = set(self.requested_scope) - effective
            if excess:
                failures.append(f"scope_exceeds_delegation:{','.join(sorted(excess))}")

        # 10. Timestamps — malformed values are failures, never exceptions.
        now_dt = now or datetime.now(timezone.utc)
        issued = _parse_iso_or_none(self.issued_at)
        if issued is None:
            failures.append("malformed_timestamp:issued_at")
        elif (issued - now_dt).total_seconds() > self.CLOCK_SKEW_SECONDS:
            failures.append("issued_in_future")
        if self.expires_at is not None:
            expires = _parse_iso_or_none(self.expires_at)
            if expires is None:
                failures.append("malformed_timestamp:expires_at")
            elif expires <= now_dt:
                failures.append("envelope_expired")
        for i, link in enumerate(self.delegation_chain):
            if link.expires_at is not None:
                link_expires = _parse_iso_or_none(link.expires_at)
                if link_expires is None:
                    failures.append(f"malformed_timestamp:delegation_link:{i}")
                elif link_expires <= now_dt:
                    failures.append(f"delegation_link_expired:{i}")

        return VerificationResult(valid=not failures, failures=tuple(failures))

    def _verify_delegation_chain(
        self, link_keys: dict[str, bytes] | None = None
    ) -> list[str]:
        failures: list[str] = []
        if not self.delegation_chain:
            failures.append("empty_delegation_chain")
            return failures
        previous_scope: set[str] | None = None
        previous_delegatee: str | None = None
        for i, link in enumerate(self.delegation_chain):
            if link_keys is not None:
                if not link.kid or not link.signature:
                    failures.append(f"unsigned_delegation_link:{i}")
                elif link.kid not in link_keys:
                    # Key absent from the registry — unknown or revoked.
                    failures.append(f"unknown_or_revoked_kid_at_link:{i}:{link.kid}")
                else:
                    unsigned = dataclass_replace(link, signature="")
                    expected = hmac.new(
                        link_keys[link.kid], unsigned.signable_payload(), hashlib.sha256
                    ).hexdigest()
                    if not hmac.compare_digest(expected, link.signature):
                        failures.append(f"link_signature_mismatch:{i}")
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
        """Parse an envelope from JSON — fail closed on malformed input.

        Any structural defect (bad JSON, missing/unknown fields, wrong types)
        raises ``ValueError`` with a stable ``malformed_envelope:`` prefix.
        Callers must treat a parse failure as a rejected envelope; nothing is
        partially constructed.
        """
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise TypeError("top-level value must be an object")
            identity = AgentIdentity(**data.pop("identity"))
            chain = tuple(
                DelegationLink(**{**link, "scope": tuple(link["scope"])})
                for link in data.pop("delegation_chain")
            )
            data["requested_scope"] = tuple(data.get("requested_scope") or ())
            data["evidence_refs"] = tuple(data.get("evidence_refs") or ())
            return cls(identity=identity, delegation_chain=chain, **data)
        except (TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
            raise ValueError(f"malformed_envelope:{exc}") from exc


def _parse_iso_or_none(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp; return None on any malformed input."""
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
