# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Runtime trust profiles for the enforcing tool-call path.

The repository supports deliberately weak configurations for local development
and research. That is useful, but it is dangerous during an external handoff:
a reviewer can otherwise exercise the legacy registry path and reasonably
assume they tested the strongest REMORA architecture.

``REMORA_RUNTIME_PROFILE`` makes that distinction explicit. The strict
profiles fail closed before execution-path policy metadata is considered.
They do not certify a deployment; they only prevent known weaker configuration
from masquerading as the review/pilot path.
"""
from __future__ import annotations

import os

from remora.profiles import (
    PROFILE_ENV,
    STRICT_PROFILES,
    RuntimeProfileError,
    current_runtime_profile,
)

__all__ = [
    "PROFILE_ENV",
    "RuntimeProfileError",
    "current_runtime_profile",
    "validate_runtime_profile_prerequisites",
]

# Name resolution lives in the leaf module remora.profiles so that
# remora.enforcement.custody can ask which profile is active without importing
# this module, which imports it. Re-exported here: existing callers are
# unaffected.
_STRICT_PROFILES = STRICT_PROFILES


def _configured(*names: str) -> bool:
    return any(os.getenv(name, "").strip() for name in names)


def validate_runtime_profile_prerequisites() -> str:
    """Fail closed when a strict handoff/pilot profile uses a weak path.

    ``review`` and ``controlled_pilot`` require:

    - a signed ToolSpec bundle and signing material;
    - an explicit trusted signing identity allowlist;
    - a deployment-owned callable registry;
    - durable execution state (Postgres or single-node SQLite);
    - a declared domain role, and the ADR-A custody split that role implies
      (property E): the authority domain holds no declared effect credential,
      the execution domain holds no lease signing material;
    - an intent resolver (property D), so the provenance floor refuses
      unresolved intents rather than every intent.

    The authority role additionally requires a ToolSpec signing key and a PDP
    signing key, so the strict PEP never receives an unsigned grant. Those are
    deliberately NOT required of the execution domain, which must not be able
    to sign the authority it verifies.

    ``controlled_pilot`` additionally requires ``REMORA_ENV=production``.

    Returns the normalized profile for callers that want to record it.
    """
    profile = current_runtime_profile()
    if profile not in _STRICT_PROFILES:
        return profile

    # Property E: the strict profiles compel the ADR-A custody split. A
    # deployment that has not split refuses to start, rather than serving an
    # execution boundary that a single interpreter cannot enforce. Validated
    # before the rest, because which prerequisites apply depends on the role.
    from remora.enforcement.custody import (
        DOMAIN_AUTHORITY,
        CustodyViolation,
        assert_custody_split,
        domain_role,
    )

    # Read the role leniently for the prerequisite pass. A deployment that
    # has configured nothing should still hear about the missing signing key
    # and durable state, not only about custody: reporting one error at a
    # time turns a single misconfiguration into several rounds of restarts.
    try:
        role = domain_role(strict=False)
    except CustodyViolation:
        role = DOMAIN_AUTHORITY

    missing: list[str] = []
    if not _configured("REMORA_TOOLSPEC_BUNDLE"):
        missing.append("REMORA_TOOLSPEC_BUNDLE")
    if not _configured("REMORA_TOOLSPEC_TRUSTED_IDENTITIES"):
        missing.append("REMORA_TOOLSPEC_TRUSTED_IDENTITIES")
    if not _configured("REMORA_TOOL_REGISTRY_MODULE"):
        missing.append("REMORA_TOOL_REGISTRY_MODULE")
    if not _configured("REMORA_PG_DSN", "REMORA_CHAIN_DB"):
        missing.append("REMORA_PG_DSN (or REMORA_CHAIN_DB)")

    # Signing material is an authority prerequisite and an executor
    # violation. The single list this replaced assumed one process did both,
    # which is the assumption the custody split removes.
    if role == DOMAIN_AUTHORITY:
        if not _configured("REMORA_TOOLSPEC_SIGNING_KEY"):
            missing.append("REMORA_TOOLSPEC_SIGNING_KEY")
        if not _configured("REMORA_PDP_SIGNING_KEY"):
            missing.append("REMORA_PDP_SIGNING_KEY")

    if missing:
        raise RuntimeProfileError(
            f"REMORA runtime profile {profile!r} refuses the legacy/weaker "
            "execution path; missing required configuration: "
            + ", ".join(missing)
        )

    # Property D: a strict profile requires the intent to resolve from a
    # deployment-owned source, and the engine hard-abstains when it does not.
    # A strict deployment with NO resolver would therefore refuse every call
    # for a reason nobody configured. Refuse at startup instead, with the
    # reason named.
    from remora.toolcall.semantic_bundle import (
        load_intent_resolution_provider,
        load_intent_resolver,
    )

    if load_intent_resolver() is None and load_intent_resolution_provider() is None:
        raise RuntimeProfileError(
            f"REMORA runtime profile {profile!r} requires an intent resolver "
            "(property D): set REMORA_SEMANTIC_BUNDLE_MODULE to a module that "
            "exposes resolve_intent or resolve_intent_detailed. Without one, "
            "every call would hard-abstain as INTENT_PROVENANCE_REQUIRED."
        )

    # Custody last, so its message is never the one hiding a plainer problem.
    assert_custody_split(strict=True)

    if profile == "controlled_pilot":
        env = os.getenv("REMORA_ENV", "").strip().lower()
        if env not in {"prod", "production"}:
            raise RuntimeProfileError(
                "REMORA runtime profile 'controlled_pilot' requires "
                "REMORA_ENV=production"
            )

    return profile
