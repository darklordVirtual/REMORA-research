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

__all__ = [
    "PROFILE_ENV",
    "RuntimeProfileError",
    "current_runtime_profile",
    "validate_runtime_profile_prerequisites",
]

PROFILE_ENV = "REMORA_RUNTIME_PROFILE"

_PROFILE_ALIASES = {
    "dev": "development",
    "development": "development",
    "research": "research",
    "shadow": "research",
    "shadow_only": "research",
    "external_review": "review",
    "review": "review",
    "pilot": "controlled_pilot",
    "controlled-pilot": "controlled_pilot",
    "controlled_pilot": "controlled_pilot",
}

_STRICT_PROFILES = frozenset({"review", "controlled_pilot"})


class RuntimeProfileError(RuntimeError):
    """The selected runtime profile is incompatible with the configuration."""


def current_runtime_profile() -> str:
    """Return the normalized runtime profile.

    Compatibility matters for an existing research repository, so an unset
    profile remains ``research`` even when ``REMORA_ENV=production``. The
    handoff and pilot quickstarts set the profile explicitly; no existing
    deployment is silently promoted into a stronger contract.
    """
    raw = os.getenv(PROFILE_ENV, "").strip().lower()
    if not raw:
        return "research"
    try:
        return _PROFILE_ALIASES[raw]
    except KeyError as exc:
        allowed = sorted(set(_PROFILE_ALIASES.values()))
        raise RuntimeProfileError(
            f"{PROFILE_ENV}={raw!r} is unknown; expected one of {allowed}"
        ) from exc


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
      the execution domain holds no lease signing material.

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
