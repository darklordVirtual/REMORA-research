# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Which signature format a process issues and accepts (RMR-CR-011).

v1 is the frozen, untagged format of PolicyDecisionToken, ExecutionLease and
the tenant audit chain: what every deployment signed before v2 existed. Its
preimages and golden vectors (``vectors/v1``) never change.

v2 is domain-separated (``remora.crypto.SignatureDomain``). A strict v2
contract (``review/v2``, ``controlled_pilot/v2``) issues v2 only and accepts
only v2 for live authority. v1 stays verifiable as historical evidence, for
offline replay and for migration diagnostics, and is never accepted to
authorize anything new under such a contract.

Everywhere else v1 remains the default, so research use and the frozen
fixtures are unchanged; ``REMORA_SIGNATURE_FORMAT=v2`` opts in.

Imports only :mod:`remora.profiles`, which is itself a leaf.
"""
from __future__ import annotations

import os

__all__ = ["ENV_SIGNATURE_FORMAT", "FORMAT_V1", "FORMAT_V2", "signature_format",
           "v1_live_refused"]

ENV_SIGNATURE_FORMAT = "REMORA_SIGNATURE_FORMAT"
FORMAT_V1 = "v1"
FORMAT_V2 = "v2"


def _strict_v2() -> bool:
    from remora.profiles import STRICT_PROFILES, current_runtime_profile, runtime_profile_contract

    return (current_runtime_profile() in STRICT_PROFILES
            and runtime_profile_contract().endswith("/v2"))


def signature_format() -> str:
    """The format this process issues: v2 under a strict v2 contract.

    Outside it, ``REMORA_SIGNATURE_FORMAT`` chooses, and unset means v1. Any
    other value raises: an unreadable choice of signature format is not a
    default.
    """
    if _strict_v2():
        return FORMAT_V2
    raw = os.environ.get(ENV_SIGNATURE_FORMAT, "").strip().lower()
    if raw in ("", FORMAT_V1):
        return FORMAT_V1
    if raw == FORMAT_V2:
        return FORMAT_V2
    raise ValueError(f"{ENV_SIGNATURE_FORMAT}={raw!r} is not one of 'v1', 'v2'")


def v1_live_refused() -> bool:
    """True when a v1 artifact may not authorize anything here (strict v2)."""
    return _strict_v2()
