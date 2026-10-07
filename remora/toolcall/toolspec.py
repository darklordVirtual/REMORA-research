# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Signed immutable ToolSpec (FT-03) — one authority for assess and dispatch.

Four sources describe a tool today and could disagree without anything
noticing: the static ``TOOL_REGISTRY`` metadata, the callable registry,
the ``SemanticBundle`` contract, and the client-asserted ``schema_valid``
flag. A ToolSpec collapses them into one signed record, so disagreement
becomes impossible rather than undetectable.

The contract is frozen in ``schemas/tool_spec_v1.yaml`` — every decision
here (HMAC with a deployment-held key, identity-allowlist revocation,
pinned-bundle staleness, fail-closed with no legacy fallback, hard schema
refusal) is recorded and tested there, so this module and the ADR cannot
drift apart.

What this module deliberately does NOT do:

- it never imports from ``remora.enforcement``, and enforcement never
  imports it. A resolved spec travels to the dispatch path as **data**,
  keeping the import direction unchanged;
- it does not hold or generate signing keys. The deployment signs; an
  agent that could sign its own spec could grant itself any capability.

Every refusal raises :class:`ToolSpecRefused` carrying one of the fourteen
published reason codes — a refusal a consumer cannot branch on is only
half a control.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

if TYPE_CHECKING:
    from remora.capabilities.ceiling import DownstreamCeiling
    from remora.crypto import SigningKey, VerificationKey

__all__ = [
    "ToolSpec",
    "ToolSpecBundle",
    "ToolSpecRefused",
    "canonical_signing_bytes",
    "sign_bundle",
    "sign_bundle_ed25519",
]

#: The frozen v1 signing model (schemas/tool_spec_v1.yaml): a deployment-held
#: HMAC key. Whoever can verify can also sign, so a strict profile refuses it.
SIGNING_ALGORITHM = "HMAC-SHA256"
#: The asymmetric model (schemas/toolspec_signing_ed25519_v1.yaml): the
#: runtime holds public keys only and cannot author an accepted bundle.
ED25519_ALGORITHM = "Ed25519"


class ToolSpecRefused(Exception):
    """A ToolSpec check failed. ``reason_code`` is a published contract."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def canonical_signing_bytes(bundle: Mapping[str, Any]) -> bytes:
    """The exact bytes a signature covers.

    Sorted keys, compact separators, UTF-8, specs ordered by
    ``(tool_id, version)``, and the ``registry_signature`` block excluded
    from its own preimage. Defined so that re-serialising a bundle — a
    different YAML writer, a different key order — cannot change what was
    signed.
    """
    specs = sorted(
        bundle.get("tool_specs", []),
        key=lambda s: (str(s.get("tool_id", "")), int(s.get("version", 0))),
    )
    payload = {
        "schema_version": bundle.get("schema_version"),
        "tool_specs": specs,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def sign_bundle(
    bundle: Mapping[str, Any],
    *,
    key: str,
    signing_identity: str,
    signed_at: str,
) -> dict[str, Any]:
    """Attach a registry signature. Deployment-side helper, not runtime."""
    signed = dict(bundle)
    signature = hmac.new(
        key.encode("utf-8"), canonical_signing_bytes(bundle), hashlib.sha256
    ).hexdigest()
    signed["registry_signature"] = {
        "signing_identity": signing_identity,
        "algorithm": SIGNING_ALGORITHM,
        "signed_at": signed_at,
        "signature": signature,
    }
    return signed


def sign_bundle_ed25519(
    bundle: Mapping[str, Any],
    *,
    key: "SigningKey",
    signed_at: str,
) -> dict[str, Any]:
    """Attach an Ed25519 registry signature. Offline signer helper, not runtime.

    The signing identity is the key's derived id, never a chosen label, and
    every spec must already name it: each spec's ``signing_identity`` is inside
    the signed bytes, so a spec cannot be moved under another signer.
    """
    from remora.crypto import SignatureDomain, sign

    kid = key.kid
    for raw in bundle.get("tool_specs", []):
        if str(raw.get("signing_identity", "")) != kid:
            raise ValueError(
                f"tool spec {raw.get('tool_id')!r} names signing identity "
                f"{raw.get('signing_identity')!r}; an Ed25519 bundle's specs must "
                f"name the signing key's id {kid!r}"
            )
    signature = sign(SignatureDomain.TOOLSPEC_BUNDLE, canonical_signing_bytes(bundle), key)
    signed = dict(bundle)
    signed["registry_signature"] = {
        "signing_identity": kid,
        "algorithm": ED25519_ALGORITHM,
        "domain": signature.domain,
        "kid": kid,
        "signed_at": signed_at,
        "signature": signature.value,
    }
    return signed


def _spec_hash(spec: Mapping[str, Any]) -> str:
    """Identity of one spec, over its full declared content."""
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


#: Bundle schema versions this loader understands. Version 2 adds the
#: optional ``downstream_capabilities`` declaration; a version-1 bundle that
#: carries one is refused rather than read with a field it never defined.
SUPPORTED_SCHEMA_VERSIONS = (1, 2, 3)

#: Schema version 3 (CR-005): how a tool reaches effects, as a signed claim.
#: MEDIATED: every effect goes through the mediator, within the declared
#: downstream ceiling. NONE: the tool reaches no effect. Absence is unknown,
#: never NONE.
EFFECT_MODES = ("MEDIATED", "NONE")
#: Whether the tool's execution domain may hold direct effect credentials.
DIRECT_EFFECT_CREDENTIAL_POLICIES = ("FORBIDDEN", "PERMITTED")


def _effect_policy(raw: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(effect_mode, direct_effect_credentials) from a v3 spec, validated."""
    mode = raw.get("effect_mode")
    if mode is not None and mode not in EFFECT_MODES:
        raise ToolSpecRefused(
            "toolspec_effect_policy_invalid",
            f"tool spec {raw.get('tool_id')!r}: effect_mode {mode!r} is not one of "
            f"{list(EFFECT_MODES)}")
    policy = raw.get("credential_policy")
    direct = None
    if policy is not None:
        if not isinstance(policy, Mapping):
            raise ToolSpecRefused(
                "toolspec_effect_policy_invalid",
                f"tool spec {raw.get('tool_id')!r}: credential_policy must be a mapping")
        direct = policy.get("direct_effect_credentials")
        if direct not in DIRECT_EFFECT_CREDENTIAL_POLICIES:
            raise ToolSpecRefused(
                "toolspec_effect_policy_invalid",
                f"tool spec {raw.get('tool_id')!r}: direct_effect_credentials {direct!r} "
                f"is not one of {list(DIRECT_EFFECT_CREDENTIAL_POLICIES)}")
    return mode, direct


def _downstream(raw: Mapping[str, Any]) -> "DownstreamCeiling | None":
    """The spec's downstream ceiling, or None when it declares none."""
    if "downstream_capabilities" not in raw:
        return None
    from remora.capabilities.ceiling import CeilingRefused, DownstreamCeiling

    entries = raw["downstream_capabilities"]
    try:
        if not isinstance(entries, (list, tuple)):
            raise CeilingRefused("downstream_capabilities is a list")
        return DownstreamCeiling.from_dict(str(raw["tool_id"]), entries)
    except (CeilingRefused, TypeError, AttributeError) as exc:
        raise ToolSpecRefused(
            "toolspec_downstream_declaration_invalid",
            f"tool spec {raw.get('tool_id')!r}: {exc}",
        ) from exc


@dataclass(frozen=True)
class ToolSpec:
    """One tool's immutable, signed declaration."""

    tool_id: str
    version: int
    callable_digest: str
    implementation_identity: str
    description: str
    description_sha256: str
    argument_schema: Mapping[str, Any]
    risk_tier: str
    action_type: str
    domain: str
    capabilities: tuple[str, ...]
    semantic_contract: Mapping[str, Any]
    credential_scope: tuple[str, ...]
    allowed_targets: tuple[str, ...]
    idempotency_contract: Mapping[str, Any]
    postcondition_reader: str | None
    compensation_tool: str | None
    timeout_policy: Mapping[str, Any]
    network_policy: Mapping[str, Any]
    signing_identity: str
    toolspec_hash: str = field(compare=False)
    #: The most the implementation may reach (schema version 2, NTA-2). None
    #: when undeclared, which is not the same as an empty ceiling: undeclared
    #: means the spec says nothing, empty means it declares no effects.
    downstream_capabilities: "DownstreamCeiling | None" = None
    #: Schema version 3 (CR-005). None when the spec does not say, which a
    #: strict v2 contract refuses: an unstated effect mode is unknown, not none.
    effect_mode: str | None = None
    direct_effect_credentials: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ToolSpec":
        missing = [
            k for k in (
                "tool_id", "version", "callable_digest",
                "implementation_identity", "description", "argument_schema",
                "risk_tier", "action_type", "domain", "capabilities",
                "semantic_contract", "credential_scope", "allowed_targets",
                "idempotency_contract", "postcondition_reader",
                "compensation_tool", "timeout_policy", "network_policy",
                "signing_identity",
            ) if k not in raw
        ]
        if missing:
            # A missing key and a declared null are different facts: the
            # first is an oversight, the second a decision.
            raise ValueError(
                f"tool spec {raw.get('tool_id')!r} is missing required "
                f"fields (declare null explicitly): {missing}"
            )
        description = str(raw["description"])
        return cls(
            tool_id=str(raw["tool_id"]),
            version=int(raw["version"]),
            callable_digest=str(raw["callable_digest"]),
            implementation_identity=str(raw["implementation_identity"]),
            description=description,
            # Computed, never read from the bundle: a declared digest is a
            # claim, a computed one is a check.
            description_sha256=hashlib.sha256(
                description.encode("utf-8")
            ).hexdigest(),
            argument_schema=MappingProxyType(dict(raw["argument_schema"])),
            risk_tier=str(raw["risk_tier"]),
            action_type=str(raw["action_type"]),
            domain=str(raw["domain"]),
            capabilities=tuple(raw["capabilities"]),
            semantic_contract=MappingProxyType(dict(raw["semantic_contract"])),
            credential_scope=tuple(raw["credential_scope"]),
            allowed_targets=tuple(raw["allowed_targets"]),
            idempotency_contract=MappingProxyType(
                dict(raw["idempotency_contract"])
            ),
            postcondition_reader=raw["postcondition_reader"],
            compensation_tool=raw["compensation_tool"],
            timeout_policy=MappingProxyType(dict(raw["timeout_policy"])),
            network_policy=MappingProxyType(dict(raw["network_policy"])),
            signing_identity=str(raw["signing_identity"]),
            toolspec_hash=_spec_hash(raw),
            downstream_capabilities=_downstream(raw),
            effect_mode=_effect_policy(raw)[0],
            direct_effect_credentials=_effect_policy(raw)[1],
        )


class ToolSpecBundle:
    """A verified set of signed ToolSpecs, and the checks that use them."""

    def __init__(
        self,
        specs: Mapping[str, ToolSpec],
        bundle_digest: str,
        *,
        signing_algorithm: str = "",
        signing_identity: str = "",
    ) -> None:
        self._specs = dict(specs)
        self.bundle_digest = bundle_digest
        #: How the accepted bundle was signed and by which identity. Recorded
        #: with every assessment so the audit trail names the signer, not only
        #: the bundle (RMR-CR-001).
        self.signing_algorithm = signing_algorithm
        self.signing_identity = signing_identity

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(
        cls,
        bundle: Mapping[str, Any] | None,
        *,
        key: str = "",
        trusted_identities: Sequence[str] = (),
        revoked_identities: Sequence[str] = (),
        pinned_bundle_digest: str | None = None,
        strict: bool = True,
        verification_keys: "Iterable[VerificationKey]" = (),
        accept_hmac: bool = True,
        require_pinned_digest: bool = False,
    ) -> "ToolSpecBundle":
        """Verify a bundle and return it, or refuse with a reason code.

        Order matters: revocation is checked before trust, because a
        revoked identity may still be present in a stale allowlist and the
        stronger statement should win. Staleness is checked after the
        signature, because "correctly signed but not current" is a
        different finding from "not signed by us" and deserves its own code.
        """
        if bundle is None:
            if strict:
                raise ToolSpecRefused(
                    "toolspec_trust_bundle_missing",
                    "strict mode is enabled but no signed ToolSpec bundle is "
                    "configured; refusing rather than falling back to the "
                    "legacy registry",
                )
            return cls({}, bundle_digest="")

        if require_pinned_digest and not pinned_bundle_digest:
            raise ToolSpecRefused(
                "toolspec_pinned_digest_required",
                "this profile requires a pinned bundle digest; a signature "
                "proves who signed, a pin proves which bundle is current",
            )

        signature_block = bundle.get("registry_signature") or {}
        identity = str(signature_block.get("signing_identity", ""))
        algorithm = str(signature_block.get("algorithm", SIGNING_ALGORITHM))

        if algorithm == ED25519_ALGORITHM:
            cls._verify_ed25519(
                bundle, signature_block, identity,
                verification_keys=verification_keys,
                revoked=tuple(revoked_identities),
            )
        elif algorithm == SIGNING_ALGORITHM and accept_hmac:
            cls._verify_hmac(
                bundle, signature_block, identity, key=key,
                trusted_identities=trusted_identities,
                revoked_identities=revoked_identities,
            )
        else:
            raise ToolSpecRefused(
                "toolspec_signature_algorithm_refused",
                f"bundle signature algorithm {algorithm!r} is not accepted here"
                + ("; a strict profile or configured Ed25519 verification keys "
                   "refuse HMAC, because a runtime that can verify an HMAC "
                   "bundle can also author one"
                   if algorithm == SIGNING_ALGORITHM else ""),
            )

        # The outer label is outside the signed bytes, so on its own it can be
        # relabeled from a revoked signer to a trusted one. Each spec's own
        # signing_identity is inside them; the label must agree with every one.
        for raw in bundle.get("tool_specs", []):
            if str(raw.get("signing_identity", "")) != identity:
                raise ToolSpecRefused(
                    "toolspec_signing_identity_mismatch",
                    f"tool spec {raw.get('tool_id')!r} is signed as "
                    f"{raw.get('signing_identity')!r}, not as the bundle's "
                    f"signing identity {identity!r}",
                )
        return cls._build(bundle, pinned_bundle_digest, algorithm, identity)

    @staticmethod
    def _verify_ed25519(
        bundle: Mapping[str, Any],
        signature_block: Mapping[str, Any],
        identity: str,
        *,
        verification_keys: "Iterable[VerificationKey]",
        revoked: Sequence[str],
    ) -> None:
        """Ed25519: the identity is the derived key id, checked against keys."""
        from remora.crypto import Signature, SignatureDomain, verify

        kid = str(signature_block.get("kid", ""))
        if identity != kid:
            raise ToolSpecRefused(
                "toolspec_signing_identity_mismatch",
                f"the bundle's signing identity {identity!r} is not its key id "
                f"{kid!r}; an Ed25519 signer is named by its key, not a label",
            )
        result = verify(
            SignatureDomain.TOOLSPEC_BUNDLE,
            canonical_signing_bytes(bundle),
            Signature.from_dict(signature_block),
            list(verification_keys),
            revoked=revoked,
        )
        if result.ok:
            return
        code = {
            "key_revoked": "toolspec_signing_identity_revoked",
            "unknown_kid": "toolspec_signing_identity_unknown",
            "key_purpose_mismatch": "toolspec_signing_identity_unknown",
            "algorithm_unsupported": "toolspec_signature_algorithm_refused",
        }.get(result.reason, "toolspec_signature_invalid")
        raise ToolSpecRefused(
            code, f"Ed25519 bundle signature refused ({result.reason}) for key {kid!r}"
        )

    @staticmethod
    def _verify_hmac(
        bundle: Mapping[str, Any],
        signature_block: Mapping[str, Any],
        identity: str,
        *,
        key: str,
        trusted_identities: Sequence[str],
        revoked_identities: Sequence[str],
    ) -> None:
        """The frozen v1 HMAC check, plus one guard: no key, no HMAC."""
        if not key:
            # An empty key is a key anyone has: a bundle HMAC-signed under it
            # would verify. Refuse rather than check against nothing.
            raise ToolSpecRefused(
                "toolspec_signature_algorithm_refused",
                "an HMAC-signed bundle cannot be verified without a configured "
                "REMORA_TOOLSPEC_SIGNING_KEY",
            )
        if identity in set(revoked_identities):
            raise ToolSpecRefused(
                "toolspec_signing_identity_revoked",
                f"signing identity {identity!r} is revoked; its signatures "
                "still verify, which is exactly why revocation is checked "
                "separately",
            )
        if identity not in set(trusted_identities):
            raise ToolSpecRefused(
                "toolspec_signing_identity_unknown",
                f"signing identity {identity!r} is not in the trust allowlist",
            )

        expected = hmac.new(
            key.encode("utf-8"), canonical_signing_bytes(bundle), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(
            expected, str(signature_block.get("signature", ""))
        ):
            raise ToolSpecRefused(
                "toolspec_signature_invalid",
                "the bundle signature does not verify; its content changed "
                "after signing",
            )

    @classmethod
    def _build(
        cls,
        bundle: Mapping[str, Any],
        pinned_bundle_digest: str | None,
        algorithm: str,
        identity: str,
    ) -> "ToolSpecBundle":
        digest = hashlib.sha256(canonical_signing_bytes(bundle)).hexdigest()
        if pinned_bundle_digest and digest != pinned_bundle_digest:
            raise ToolSpecRefused(
                "toolspec_bundle_stale",
                "the bundle is correctly signed but is not the pinned one; a "
                "signature proves authenticity, never currency",
            )

        schema_version = bundle.get("schema_version")
        if (isinstance(schema_version, bool) or not isinstance(schema_version, int)
                or schema_version not in SUPPORTED_SCHEMA_VERSIONS):
            raise ToolSpecRefused(
                "toolspec_schema_version_unsupported",
                f"bundle schema_version {schema_version!r} is not one of "
                f"{SUPPORTED_SCHEMA_VERSIONS}; it was signed, and never checked",
            )
        specs: dict[str, ToolSpec] = {}
        for raw in bundle.get("tool_specs", []):
            if schema_version < 2 and "downstream_capabilities" in raw:
                raise ToolSpecRefused(
                    "toolspec_downstream_requires_v2",
                    f"tool spec {raw.get('tool_id')!r} declares downstream "
                    "capabilities in a schema_version 1 bundle",
                )
            if schema_version < 3 and ("effect_mode" in raw or "credential_policy" in raw):
                raise ToolSpecRefused(
                    "toolspec_effect_policy_requires_v3",
                    f"tool spec {raw.get('tool_id')!r} declares an effect policy in a "
                    f"schema_version {schema_version} bundle",
                )
            spec = ToolSpec.from_mapping(raw)
            if spec.tool_id in specs:
                raise ValueError(
                    f"duplicate tool_id {spec.tool_id!r} in bundle; flat ids "
                    "were chosen over namespacing, so uniqueness is enforced "
                    "here rather than assumed"
                )
            specs[spec.tool_id] = spec
        return cls(specs, bundle_digest=digest, signing_algorithm=algorithm,
                   signing_identity=identity)

    # -- lookups and checks ------------------------------------------------

    def tool_specs(self) -> tuple[ToolSpec, ...]:
        """Every spec in the verified bundle, ordered by tool id."""
        return tuple(self._specs[k] for k in sorted(self._specs))

    def get(self, tool_id: str) -> ToolSpec:
        spec = self._specs.get(tool_id)
        if spec is None:
            raise ToolSpecRefused(
                "toolspec_unknown_tool",
                f"no signed spec exists for {tool_id!r}",
            )
        return spec

    def verify_callable(self, tool_id: str, digest: str) -> None:
        """The registered callable must be the one the spec attests."""
        spec = self.get(tool_id)
        if not hmac.compare_digest(spec.callable_digest, digest):
            raise ToolSpecRefused(
                "toolspec_callable_digest_mismatch",
                f"{tool_id}: the registered callable is not the one this spec "
                "attests",
            )

    def verify_credential_scope(
        self, tool_id: str, requested: Sequence[str]
    ) -> None:
        """Dispatch may use no more scope than the spec declares."""
        spec = self.get(tool_id)
        excess = set(requested) - set(spec.credential_scope)
        if excess:
            raise ToolSpecRefused(
                "toolspec_credential_scope_mismatch",
                f"{tool_id}: dispatch requested scope beyond the declaration: "
                f"{sorted(excess)}",
            )

    def verify_target(self, tool_id: str, target: str) -> None:
        spec = self.get(tool_id)
        if target not in spec.allowed_targets:
            raise ToolSpecRefused(
                "toolspec_target_not_allowed",
                f"{tool_id}: target {target!r} is outside "
                f"{list(spec.allowed_targets)}",
            )

    def verify_same_spec(self, tool_id: str, expected_hash: str) -> None:
        """The spec at dispatch must be the spec that was assessed."""
        spec = self.get(tool_id)
        if not hmac.compare_digest(spec.toolspec_hash, expected_hash):
            raise ToolSpecRefused(
                "toolspec_changed_between_assess_and_dispatch",
                f"{tool_id}: the spec changed after assessment; the action "
                "about to run is not the action that was reviewed",
            )

    def validate_arguments(
        self, tool_id: str, arguments: Mapping[str, Any]
    ) -> None:
        """Validate against the spec's JSON Schema. Failure is a REFUSAL.

        Decided in PR 1: ``schema_valid`` was downgrade-only because
        nothing validated it. Once validation is computed, a computed
        failure that merely lowers trust would let a malformed call run.

        The subset of JSON Schema enforced here is deliberately small and
        explicit — required, additionalProperties, and scalar types — so
        that what is checked is legible. A spec relying on constructs
        outside it would be validated less strictly than its author
        expects, which is why the loader is the place to widen this, not
        the caller.
        """
        spec = self.get(tool_id)
        schema = spec.argument_schema
        problems: list[str] = []

        properties = schema.get("properties", {}) or {}
        for name in schema.get("required", []) or []:
            if name not in arguments:
                problems.append(f"missing required argument {name!r}")
        if schema.get("additionalProperties") is False:
            for name in arguments:
                if name not in properties:
                    problems.append(f"unexpected argument {name!r}")
        _TYPES: dict[str, type | tuple[type, ...]] = {
            "string": str, "integer": int, "number": (int, float),
            "boolean": bool, "object": dict, "array": (list, tuple),
        }
        for name, value in arguments.items():
            declared = (properties.get(name) or {}).get("type")
            expected = _TYPES.get(str(declared)) if declared else None
            if expected is None:
                continue
            if declared == "integer" and isinstance(value, bool):
                problems.append(f"{name!r}: expected integer, got boolean")
                continue
            if not isinstance(value, expected):
                problems.append(
                    f"{name!r}: expected {declared}, got "
                    f"{type(value).__name__}"
                )
        if problems:
            raise ToolSpecRefused(
                "toolspec_arguments_schema_invalid",
                f"{tool_id}: " + "; ".join(problems),
            )

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, tool_id: object) -> bool:
        return tool_id in self._specs
