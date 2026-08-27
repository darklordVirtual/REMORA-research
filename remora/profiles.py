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
    "PROFILE_ENV",
    "STRICT_PROFILES",
    "RuntimeProfileError",
    "current_runtime_profile",
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

STRICT_PROFILES = frozenset({"review", "controlled_pilot"})


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
