# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""AgentAvow signed tool manifest to REMORA authorization: one foreign edge (E8).

The adapter is thin on purpose::

    signed tool manifest (foreign artifact)
        -> verify_manifest: signature under a deployment-held key, digest consistency
        -> ObservedToolDefinition (normalized evidence) + external-evidence-ref-v1
        -> bind_to_authorization: the observed digest against the toolspec_hash
           inside an authentic ExecutionLease
        -> interop-result shaped verdict

What it establishes when it says ESTABLISHED: the tool definition a named
signer attested is, by digest, the tool definition bound into the signed
authorization for an exact call. What it never does: admit the manifest as
context, change a decision, or mint authority. The evidence reference it
emits is ``UNADMITTED`` and stays so unless a deployment-owned admission
step, reviewed and listed in ``authority_integrations.json``, says otherwise
(FED-INV-005).

The wire format is REMORA's assumption, recorded as profile v0 in the fixture
package. AgentAvow has not confirmed it; until it does, every result on this
edge is EXPERIMENTAL in the interop matrix regardless of its status.

Keys come from the caller. The adapter holds no registry and resolves no
identifier: a signer whose key the deployment did not supply is
``signer_unknown`` whatever registry lists its project (FED-INV-001).
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
from typing import Any, Mapping

from remora.enforcement.lease import ExecutionLease
from remora.interop.jcs import canonicalise

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover - the dev and security extras carry it
    InvalidSignature = None  # type: ignore[assignment,misc]
    Ed25519PublicKey = None  # type: ignore[assignment,misc]

__all__ = [
    "PROFILE_ID",
    "BindingResult",
    "ManifestVerification",
    "ObservedToolDefinition",
    "bind_to_authorization",
    "evaluate_fixture_case",
    "verify_manifest",
]

PROFILE_ID = "remora-agentavow-tool-manifest-profile-v0"
_ALGORITHMS = ("ed25519",)
_REQUIRED = ("kid", "tool_definition", "tool_definition_digest")

ESTABLISHES = (
    "the attested tool definition's digest equals the tool-definition identity bound into the authentic authorization",
)
DOES_NOT_ESTABLISH = (
    "that the signer is trustworthy or that its project is",
    "that the tool definition is semantically correct or safe",
    "that the runtime exposed exactly this definition (E7 is a separate claim)",
    "that the authorized call executed or had an effect",
    "production deployment safety",
    "any REMORA decision: the evidence reference is UNADMITTED",
)


@dataclasses.dataclass(frozen=True)
class ObservedToolDefinition:
    """Normalized evidence: what the manifest, once verified, says."""

    profile: str
    manifest_id: str
    issuer: str
    kid: str
    issued_at: str
    tool_definition: Mapping[str, Any]
    digest: str
    manifest_digest: str

    def evidence_ref(self, producer: str) -> dict[str, Any]:
        """An ``external-evidence-ref-v1`` record, always UNADMITTED."""
        return {
            "schema_version": "remora-external-evidence-ref-v1",
            "producer": producer,
            "artifact_ref": self.manifest_id,
            "artifact_digest": "sha256:" + self.manifest_digest,
            "native_claim": "tool_definition_attested",
            "native_result": "ATTESTED",
            "subject_class": "tool_definition",
            "subject_id": self.tool_definition.get("name"),
            "temporal_scope": self.issued_at,
            "verification": {
                "verifier": "remora.interop.agentavow",
                "implementation_diversity": "NOT_CLASSIFIED",
                "operator": "NOT_CLASSIFIED",
                "independence": "NOT_CLASSIFIED",
            },
            "claim_ceiling": (
                "Establishes only that a key the deployment holds signed this tool definition. "
                "It does not establish semantic correctness, runtime exposure, execution or any REMORA decision."
            ),
            "admission_state": "UNADMITTED",
        }


@dataclasses.dataclass(frozen=True)
class ManifestVerification:
    ok: bool
    reason: str
    observed: ObservedToolDefinition | None = None


@dataclasses.dataclass(frozen=True)
class BindingResult:
    status: str
    reason: str
    establishes: tuple[str, ...]
    does_not_establish: tuple[str, ...]
    evidence_ref: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _key_bytes(value: bytes | str) -> bytes:
    return value if isinstance(value, bytes) else base64.b64decode(value)


def verify_manifest(manifest: Mapping[str, Any], trusted_signers: Mapping[str, bytes | str]) -> ManifestVerification:
    """Signature under a caller-supplied key, then digest consistency.

    Every failure is a distinct reason and none is a pass. A missing
    ``cryptography`` is ``verifier_unavailable``, not a skipped check.
    """
    if Ed25519PublicKey is None:
        return ManifestVerification(False, "verifier_unavailable")
    body = {k: v for k, v in manifest.items() if k != "signature"}
    signature = manifest.get("signature")
    if any(member not in body for member in _REQUIRED) or not isinstance(body.get("tool_definition"), Mapping):
        return ManifestVerification(False, "manifest_malformed")
    if not isinstance(signature, Mapping) or "alg" not in signature or "value" not in signature:
        return ManifestVerification(False, "manifest_malformed")
    if signature["alg"] not in _ALGORITHMS:
        return ManifestVerification(False, "algorithm_unsupported")
    public = trusted_signers.get(body["kid"])
    if public is None:
        return ManifestVerification(False, "signer_unknown")
    try:
        preimage = canonicalise(body)
        Ed25519PublicKey.from_public_bytes(_key_bytes(public)).verify(base64.b64decode(signature["value"]), preimage)
    except (InvalidSignature, ValueError, TypeError):
        return ManifestVerification(False, "signature_invalid")
    digest = hashlib.sha256(canonicalise(body["tool_definition"])).hexdigest()
    if body["tool_definition_digest"] != "sha256:" + digest:
        return ManifestVerification(False, "manifest_inconsistent")
    observed = ObservedToolDefinition(
        profile=str(body.get("profile", PROFILE_ID)),
        manifest_id=str(body.get("manifest_id", "")),
        issuer=str(body.get("issuer", "")),
        kid=str(body["kid"]),
        issued_at=str(body.get("issued_at", "")),
        tool_definition=dict(body["tool_definition"]),
        digest=digest,
        manifest_digest=hashlib.sha256(canonicalise(dict(manifest))).hexdigest(),
    )
    return ManifestVerification(True, "verified", observed)


def bind_to_authorization(
    verification: ManifestVerification,
    lease: ExecutionLease,
    *,
    producer: str = "AgentAvow",
    now: str | None = None,
) -> BindingResult:
    """The observed digest against ``toolspec_hash`` in an authentic lease.

    The lease is checked with ``verify_authenticity`` only: this edge binds a
    definition to an authorization, not a call to a dispatch. The call binding
    is exact-call-binding-v1's claim and is not re-stated here.
    """
    def _result(status: str, reason: str) -> BindingResult:
        ref = verification.observed.evidence_ref(producer) if verification.observed else None
        return BindingResult(status, reason, ESTABLISHES if status == "ESTABLISHED" else (), DOES_NOT_ESTABLISH, ref)

    if not verification.ok:
        return _result("NOT_ESTABLISHED", verification.reason)
    authenticity = lease.verify_authenticity(now=now)
    if not authenticity.verified:
        return _result("NOT_ESTABLISHED", "authorization_unverifiable")
    assert verification.observed is not None
    if not lease.toolspec_hash:
        return _result("NOT_ESTABLISHED", "authorization_unbound_to_definition")
    if lease.toolspec_hash == verification.observed.digest:
        return _result("ESTABLISHED", "digest_bound")
    return _result("CONTRADICTED", "digest_mismatch")


def evaluate_fixture_case(case: Mapping[str, Any], trusted_signers: Mapping[str, bytes | str]) -> dict[str, Any]:
    """One fixture case through the adapter with a real lease on the REMORA
    side. The process must hold a lease signing key; an unsigned lease is the
    fixture's ``integrity: unsigned`` and is produced from a signed one."""
    authorization = case["authorization"]
    lease = ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-7",
        tool_name="update_ticket", arguments={"ticket_id": "T-1041", "status": "closed"},
        target_environment="production", policy_bundle_hash="sha256:" + "f" * 64,
        issued_at="2026-10-04T12:00:00+00:00",
        toolspec_hash=authorization["toolspec_hash"], toolspec_version=3,
    )
    if authorization.get("integrity", "intact") == "unsigned":
        lease = dataclasses.replace(lease, signature="", is_signed=False)
    elif authorization.get("integrity") == "tampered":
        lease = dataclasses.replace(lease, signature="00" * 32)
    verification = verify_manifest(case["manifest"], trusted_signers)
    binding = bind_to_authorization(verification, lease, now="2026-10-04T12:00:30+00:00")
    return {"verdict": binding.status, "reason": binding.reason}
