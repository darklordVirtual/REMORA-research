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
            _TOOLSPECS = ToolSpecBundle.load(
                raw,
                key=environ.get("REMORA_TOOLSPEC_SIGNING_KEY", ""),
                trusted_identities=identities,
                revoked_identities=revoked,
                pinned_bundle_digest=(
                    environ.get("REMORA_TOOLSPEC_PINNED_DIGEST", "").strip()
                    or None
                ),
            )
    return _TOOLSPECS


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
