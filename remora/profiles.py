# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Runtime profile resolution, as a leaf module.

Which profile is active is a question both the enforcement layer and the
tool-call layer need to ask, and neither should have to import the other to
ask it. ``remora.toolcall.runtime_profile`` owns the *prerequisites* a strict
profile imposes; this module owns only the name resolution, imports nothing
from ``remora``, and therefore cannot participate in an import cycle.

``remora.toolcall.runtime_profile`` re-exports everything here, so existing
callers are unaffected.
"""
from __future__ import annotations

import os

__all__ = [
    "DEPLOYMENT_ENV",
    "PROFILE_ENV",
    "STRICT_PROFILES",
    "RuntimeProfileError",
    "current_runtime_profile",
    "deployment_environment",
]

#: REMORA_ENV: which deployment environment this process runs in.
DEPLOYMENT_ENV = "REMORA_ENV"

_DEPLOYMENT_ALIASES = {
    "development": "development",
    "dev": "development",
    "production": "production",
    "prod": "production",
}

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

STRICT_PROFILES = frozenset({"review", "controlled_pilot"})


class RuntimeProfileError(RuntimeError):
    """The selected runtime profile is incompatible with the configuration."""


def deployment_environment() -> str:
    """``development`` or ``production``: the one reading of REMORA_ENV.

    RMR-CR-003. Readers used to disagree: a value that was neither a
    development nor a production spelling (``staging``, a typo, an empty
    value) was "not development" to the authentication path and "not
    production" to the startup guard, so it got the weaker half of each.
    Every reader now asks this function, and an unknown value is refused
    instead of being read as either. Unset means development, as documented.
    Set but blank is refused like any other unknown value: the old readers
    treated it as "not development", so reading it as development now would
    quietly start trusting the self-asserted role header.
    """
    raw = os.getenv(DEPLOYMENT_ENV)
    if raw is None:
        return "development"
    value = raw.strip().lower()
    try:
        return _DEPLOYMENT_ALIASES[value]
    except KeyError as exc:
        raise RuntimeProfileError(
            f"{DEPLOYMENT_ENV}={raw!r} is unknown; expected development or "
            "production. An unknown value is refused rather than read as "
            "either, because each reader would pick a different one."
        ) from exc


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
