# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Custody split as a deterministic hard guard (Agent Authority property E).

The bypass suite established two things about a single-process deployment:
the guarded callable can be pulled straight off the dispatcher, and a
co-resident process reads the environment without importing anything. Both
are properties of the interpreter, not defects in the dispatcher, so no
amount of care inside ``GovernedToolDispatcher`` removes them.

What can be removed is the *configuration* in which they matter. ADR-A
already describes the split: the authority domain mints leases and holds no
downstream credential, the execution domain holds the credentials and cannot
sign. Until now that split was a deployment convention. This module makes it
a prerequisite, so a strict profile that has not split custody refuses to
run rather than serving a boundary it cannot enforce.

Three rules, applied only under the strict runtime profiles
(``review``, ``controlled_pilot``):

1. The domain role must be stated. Defaulting is what let a single process
   be both halves without anyone choosing it.
2. An **authority** process must hold no declared effect credential, and
   must not hold tool callables. A process that can authorize and also
   perform needs no bypass.
3. An **executor** process must hold no lease signing material, and must
   hold the effect credentials it dispatches with. A process that can sign
   its own authorization is not verifying anything.

The deployment declares which environment variables are effect credentials
via ``REMORA_EFFECT_CREDENTIAL_ENV_NAMES``. Under a strict profile the
declaration may not be empty: a guard with nothing to check would pass
every deployment, which is the failure mode this module exists to end.
"""
from __future__ import annotations

import os

from remora.errors import RemoraError
from remora.profiles import STRICT_PROFILES, current_runtime_profile

__all__ = [
    "ENV_DOMAIN_ROLE",
    "ENV_EFFECT_CREDENTIALS",
    "DOMAIN_AUTHORITY",
    "DOMAIN_EXECUTOR",
    "CustodyViolation",
    "declared_effect_credentials",
    "domain_role",
    "custody_is_enforced",
    "assert_custody_split",
    "assert_may_hold_tool_callables",
    "assert_may_mint_authority",
]

ENV_DOMAIN_ROLE = "REMORA_EXECUTION_DOMAIN_ROLE"
ENV_EFFECT_CREDENTIALS = "REMORA_EFFECT_CREDENTIAL_ENV_NAMES"

DOMAIN_AUTHORITY = "authority"
DOMAIN_EXECUTOR = "executor"

#: Material that lets a process mint its own authorization. An executor
#: holding any of these has renamed the split rather than made one.
_SIGNING_ENVS = (
    "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
    "REMORA_LEASE_SIGNING_KEY",
    "REMORA_PDP_SIGNING_KEY",
)

#: Verification material the executor is supposed to hold instead.
_VERIFY_ENV = "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC"


class CustodyViolation(RemoraError, RuntimeError):
    """The process holds a combination of secrets its role forbids.

    Raised at configuration time rather than at dispatch time. A custody
    error discovered on the request path has already been serving requests.
    """

    code = "custody_violation"
    category = "enforcement"


def _present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def custody_is_enforced() -> bool:
    """True when the active runtime profile compels the split."""
    return current_runtime_profile() in STRICT_PROFILES


def declared_effect_credentials() -> tuple[str, ...]:
    """Environment variable names the deployment calls effect credentials."""
    raw = os.environ.get(ENV_EFFECT_CREDENTIALS, "")
    return tuple(sorted({part.strip() for part in raw.split(",") if part.strip()}))


def domain_role(*, strict: bool | None = None) -> str:
    """The declared role of this process.

    Outside the strict profiles an unset role remains ``authority``, so
    library and research use is unchanged. Under a strict profile an unset
    role is refused: the split has to be a decision somebody made.
    """
    enforced = custody_is_enforced() if strict is None else strict
    value = os.environ.get(ENV_DOMAIN_ROLE, "").strip().lower()
    if value in (DOMAIN_AUTHORITY, DOMAIN_EXECUTOR):
        return value
    if value:
        raise CustodyViolation(
            f"{ENV_DOMAIN_ROLE}={value!r} is neither {DOMAIN_AUTHORITY!r} "
            f"nor {DOMAIN_EXECUTOR!r}"
        )
    if enforced:
        raise CustodyViolation(
            f"a strict runtime profile requires {ENV_DOMAIN_ROLE} to be set "
            f"to {DOMAIN_AUTHORITY!r} or {DOMAIN_EXECUTOR!r}; an unset role "
            "means one process is silently both halves of the custody split"
        )
    return DOMAIN_AUTHORITY


def assert_custody_split(*, strict: bool | None = None) -> str:
    """Refuse to proceed unless this process holds only its own secrets.

    Returns the validated role. A no-op outside the strict profiles.
    """
    enforced = custody_is_enforced() if strict is None else strict
    if not enforced:
        return domain_role(strict=False)

    role = domain_role(strict=True)
    declared = declared_effect_credentials()
    if not declared:
        raise CustodyViolation(
            f"a strict runtime profile requires {ENV_EFFECT_CREDENTIALS} to "
            "name at least one effect credential; with nothing declared this "
            "guard would pass every deployment, including one that never "
            "split custody at all"
        )

    problems: list[str] = []
    if role == DOMAIN_AUTHORITY:
        held = [name for name in declared if _present(name)]
        if held:
            problems.append(
                "the authority domain holds effect credential(s) "
                + ", ".join(held)
                + "; a process that authorizes and also performs needs no "
                "bypass path to be bypassed"
            )
    else:
        signing = [name for name in _SIGNING_ENVS if _present(name)]
        if signing:
            problems.append(
                "the execution domain holds lease signing material "
                + ", ".join(signing)
                + "; a process that can sign its own authorization verifies "
                "nothing"
            )
        if not _present(_VERIFY_ENV):
            problems.append(
                f"the execution domain must hold {_VERIFY_ENV} to verify "
                "leases it did not mint"
            )
        absent = [name for name in declared if not _present(name)]
        if absent:
            problems.append(
                "the execution domain is missing effect credential(s) "
                + ", ".join(absent)
                + "; it cannot be the only holder of a credential it does "
                "not have"
            )

    if problems:
        raise CustodyViolation(
            f"custody split violated for role {role!r}: " + "; ".join(problems)
        )
    return role


def assert_may_hold_tool_callables() -> None:
    """Refuse tool registration in a process that must not perform effects.

    This is what turns the in-process extraction bypass into a configuration
    that cannot exist under a strict profile. The callable is unreachable
    from agent-facing code because it is not in that process at all, which
    is the only form of custody a single interpreter can offer.
    """
    if not custody_is_enforced():
        return
    role = domain_role(strict=True)
    if role == DOMAIN_AUTHORITY:
        raise CustodyViolation(
            "the authority domain must not register tool callables: under a "
            "strict profile the callable, and the credential it closes over, "
            "belong to the execution domain. Set "
            f"{ENV_DOMAIN_ROLE}={DOMAIN_EXECUTOR!r} in the process that "
            "dispatches."
        )


def assert_may_mint_authority() -> None:
    """Refuse lease minting in a process that must only verify."""
    if not custody_is_enforced():
        return
    role = domain_role(strict=True)
    if role == DOMAIN_EXECUTOR:
        raise CustodyViolation(
            "the execution domain must not mint leases: it verifies "
            "authority it did not issue. A lease minted here would be a "
            "lease the executor authorized for itself."
        )
