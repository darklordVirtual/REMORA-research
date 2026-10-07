# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Effect-mediation policy for strict deployments (CR-005).

Under the strict v2 contract every privileged tool reaches effects only
through REMORA: the tool code runs in an execution domain that holds no
effect credential, and each effect is requested from the mediator within the
ceiling its signed ToolSpec declares. A tool that reaches no effect must say
so in its signed spec. Absence of a declaration is never read as "no
effects".

The rules, applied to the signed spec and to how the tool was registered:

- missing ``effect_mode``                        -> ``effect_mode_missing``
- MEDIATED without downstream capabilities        -> ``effect_capabilities_missing``
- MEDIATED registered with ``mediated=False``     -> ``effect_mediation_not_registered``
- NONE with non-empty downstream capabilities     -> ``effect_none_declares_capabilities``
- NONE for a tool that is not signed read-only    -> ``effect_none_for_consequential_tool``
- NONE registered as mediated                     -> ``effect_none_registered_mediated``
- direct effect credentials other than FORBIDDEN  -> ``direct_effect_credentials_not_forbidden``

``NONE`` stays a signed claim, not proof: an empty ceiling does not show that
the implementation has no hidden effect. That is why it is accepted only for
read-only tools. Whether a deployment can reach effect credentials outside the
mediator is a separate, deployment-level property and stays NOT_ESTABLISHED.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.toolcall.toolspec import ToolSpec

__all__ = ["effect_policy_refusal", "static_effect_policy_refusal"]


def _read_only(spec: "ToolSpec") -> bool:
    from remora.policy.decision_engine import _READ_ONLY_ACTION_TYPES

    return (spec.action_type or "").strip().lower() in _READ_ONLY_ACTION_TYPES


def _capabilities(spec: "ToolSpec") -> tuple[Any, ...] | None:
    ceiling = spec.downstream_capabilities
    return None if ceiling is None else tuple(ceiling.capabilities)


def static_effect_policy_refusal(spec: "ToolSpec") -> str | None:
    """The refusal a signed spec earns on its own, before registration."""
    mode = spec.effect_mode
    if mode is None:
        return "effect_mode_missing"
    capabilities = _capabilities(spec)
    if mode == "MEDIATED" and not capabilities:
        return "effect_capabilities_missing"
    if mode == "NONE":
        if capabilities:
            return "effect_none_declares_capabilities"
        if not _read_only(spec):
            return "effect_none_for_consequential_tool"
    if spec.direct_effect_credentials != "FORBIDDEN":
        return "direct_effect_credentials_not_forbidden"
    return None


def effect_policy_refusal(spec: "ToolSpec", *, mediated: bool) -> str | None:
    """The refusal for a spec as registered: static rules, then registration."""
    refusal = static_effect_policy_refusal(spec)
    if refusal is not None:
        return refusal
    if spec.effect_mode == "MEDIATED" and not mediated:
        return "effect_mediation_not_registered"
    if spec.effect_mode == "NONE" and mediated:
        return "effect_none_registered_mediated"
    return None
