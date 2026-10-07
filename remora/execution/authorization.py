# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Authoritative-context authorization helpers (issue #241, slice 3).

ToolSpec bundle loading/verification and the assessed-record read-back moved
from servers/execution_api.py. Refusals here are ``ToolSpecRefused``; the
route layer owns all HTTP conversion (it maps them to status 409).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from remora.toolcall.toolspec import ToolSpecBundle

#: Comma-separated Ed25519 public keys (hex or base64) trusted to sign ToolSpec
#: bundles. A runtime configured with these can verify bundles and author none.
ENV_TOOLSPEC_VERIFY_KEYS = "REMORA_TOOLSPEC_VERIFY_KEYS"
#: Outside strict profiles, keep accepting HMAC bundles after Ed25519 keys are
#: configured. Off by default, so the migration window is a decision.
ENV_TOOLSPEC_ACCEPT_HMAC = "REMORA_TOOLSPEC_ACCEPT_HMAC"

# Cache keyed on the configured bundle path, so a load failure is raised on
# the first request rather than swallowed at import — a deployment that
# mis-signs its bundle should find out loudly.
_TOOLSPECS: ToolSpecBundle | None = None
_TOOLSPECS_SPEC: str | None = None


def load_toolspec_bundle(environ: Any) -> ToolSpecBundle | None:
    """The verified bundle for this configuration, or None when unset."""
    global _TOOLSPECS, _TOOLSPECS_SPEC
    path = environ.get("REMORA_TOOLSPEC_BUNDLE", "").strip()
    if _TOOLSPECS_SPEC != path:
        _TOOLSPECS_SPEC = path
        if not path:
            _TOOLSPECS = None
        else:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            identities = [
                i.strip() for i in
                environ.get("REMORA_TOOLSPEC_TRUSTED_IDENTITIES", "").split(",")
                if i.strip()
            ]
            revoked = [
                i.strip() for i in
                environ.get("REMORA_TOOLSPEC_REVOKED_IDENTITIES", "").split(",")
                if i.strip()
            ]
            policy = toolspec_trust_policy(environ)
            _TOOLSPECS = ToolSpecBundle.load(
                raw,
                key=environ.get("REMORA_TOOLSPEC_SIGNING_KEY", ""),
                trusted_identities=identities,
                revoked_identities=revoked,
                pinned_bundle_digest=(
                    environ.get("REMORA_TOOLSPEC_PINNED_DIGEST", "").strip()
                    or None
                ),
                verification_keys=policy["verification_keys"],
                accept_hmac=policy["accept_hmac"],
                require_pinned_digest=policy["strict"],
            )
            # Startup evidence: which bundle was accepted, how it was signed
            # and by whom. Every assessment record carries the bundle digest,
            # so this event ties each decision to a named signer.
            from remora.observability.events import governance_event

            governance_event(
                "toolspec.bundle_accepted",
                # Named *_hash / *_id so redaction keeps the values legible.
                bundle_hash=_TOOLSPECS.bundle_digest,
                signing_algorithm=_TOOLSPECS.signing_algorithm,
                signer_key_id=_TOOLSPECS.signing_identity,
                pinned=bool(environ.get("REMORA_TOOLSPEC_PINNED_DIGEST", "").strip()),
                strict=policy["strict"],
            )
    return _TOOLSPECS


def toolspec_trust_policy(environ: Any) -> dict[str, Any]:
    """How this process may verify ToolSpec bundles (RMR-CR-001).

    - Strict profile (review, controlled_pilot): Ed25519 only, pinned digest
      required. HMAC is refused, because a runtime that verifies an HMAC
      bundle holds the key that authors one.
    - Otherwise, with Ed25519 keys configured: Ed25519, and HMAC only when
      ``REMORA_TOOLSPEC_ACCEPT_HMAC`` is set.
    - Otherwise: the frozen v1 HMAC model, unchanged.
    """
    from remora.crypto import SignatureDomain, VerificationKey
    from remora.profiles import STRICT_PROFILES, current_runtime_profile

    raw_keys = [
        k.strip() for k in environ.get(ENV_TOOLSPEC_VERIFY_KEYS, "").split(",")
        if k.strip()
    ]
    keys = [
        VerificationKey.from_text(k, [SignatureDomain.TOOLSPEC_BUNDLE])
        for k in raw_keys
    ]
    strict = current_runtime_profile() in STRICT_PROFILES
    compat = environ.get(ENV_TOOLSPEC_ACCEPT_HMAC, "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    accept_hmac = not strict and (not keys or compat)
    return {"verification_keys": keys, "accept_hmac": accept_hmac, "strict": strict}


def reset_toolspec_bundle_cache() -> None:
    """Test hook: drop the cached bundle (e.g. after env changes)."""
    global _TOOLSPECS, _TOOLSPECS_SPEC
    _TOOLSPECS = None
    _TOOLSPECS_SPEC = None


def resolve_toolspec(
    bundle: ToolSpecBundle | None,
    tool_name: str,
    arguments: dict[str, Any],
    target_environment: str,
) -> dict[str, Any]:
    """Enforce the signed spec for one call and return its identity block.

    Raises ``ToolSpecRefused`` on any refusal — the route layer converts it
    to HTTP 409 with the published reason code first in the detail. With no
    bundle configured it reports enforced=False rather than pretending a
    spec was checked.
    """
    if bundle is None:
        return {"enforced": False, "tool_id": tool_name, "version": 0,
                "hash": "", "bundle_digest": ""}
    spec = bundle.get(tool_name)
    bundle.verify_target(tool_name, target_environment)
    bundle.validate_arguments(tool_name, arguments)
    return {
        "enforced": True,
        "tool_id": spec.tool_id,
        "version": spec.version,
        "hash": spec.toolspec_hash,
        "bundle_digest": bundle.bundle_digest,
        # Which argument the spec DECLARES as the target. Proposal lineage
        # keys on it so two calls about different objects are not counted
        # as one attempt retried; without a spec there is nothing to
        # declare it, and the lineage record says the key is coarser.
        "argument_roles": dict(
            (spec.semantic_contract or {}).get("argument_roles", {})
        ),
    }


def assessed_toolspec_for_proposal(
    chain: Any, tenant: str, proposal_id: str
) -> str:
    """The ToolSpec hash recorded at assessment for one proposal.

    The direct-ACCEPT path has no review item to key on, so the canonical
    proposal identity the grant carries is the key. Same discipline as
    :func:`assessed_record`: read back from the chain, and called BEFORE any
    execute transaction opens.
    """
    if not proposal_id:
        return ""
    for entry in chain.entries(tenant):
        payload = entry.payload
        if payload.get("event") == "assessed" and                 payload.get("proposal_id") == proposal_id:
            return str(payload.get("toolspec_hash") or "")
    return ""


def assessed_record(chain: Any, tenant: str, item_id: str) -> tuple[str, str]:
    """The (toolspec_hash, proposal_id) recorded at assessment.

    Read back from the audit chain rather than carried in the request: the
    caller must not be able to tell us which spec it was assessed under,
    or the comparison proves nothing.

    Must be called BEFORE the execute transaction opens. Reading the chain
    inside that transaction deadlocks against SQLite's BEGIN EXCLUSIVE on
    the same database file — the same trap the outbox hit, found again by
    the durable-mode tests.
    """
    if not item_id:
        return "", ""
    for entry in chain.entries(tenant):
        payload = entry.payload
        if payload.get("event") == "assessed" and \
                payload.get("review_item_id") == item_id:
            return (str(payload.get("toolspec_hash") or ""),
                    str(payload.get("proposal_id") or ""))
    return "", ""
