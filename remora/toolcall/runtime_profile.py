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

import logging
import os
from typing import Any

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
    # RMR-CR-001: a strict runtime verifies ToolSpec bundles with public keys
    # it cannot sign with, and accepts only the pinned bundle.
    if not _configured("REMORA_TOOLSPEC_VERIFY_KEYS"):
        missing.append("REMORA_TOOLSPEC_VERIFY_KEYS")
    if not _configured("REMORA_TOOLSPEC_PINNED_DIGEST"):
        missing.append("REMORA_TOOLSPEC_PINNED_DIGEST")
    if not _configured("REMORA_TOOL_REGISTRY_MODULE"):
        missing.append("REMORA_TOOL_REGISTRY_MODULE")
    if not _configured("REMORA_PG_DSN", "REMORA_CHAIN_DB"):
        missing.append("REMORA_PG_DSN (or REMORA_CHAIN_DB)")
    # RMR-CR-003: a strict profile derives tenant and role from a credential
    # table. Single-token and no-auth modes take both from request headers.
    if not _configured("REMORA_API_TOKENS"):
        missing.append("REMORA_API_TOKENS")

    # Signing material is an authority prerequisite and an executor
    # violation. The single list this replaced assumed one process did both,
    # which is the assumption the custody split removes.
    if role == DOMAIN_AUTHORITY:
        if not _configured("REMORA_PDP_SIGNING_KEY"):
            missing.append("REMORA_PDP_SIGNING_KEY")

    if missing:
        raise RuntimeProfileError(
            f"REMORA runtime profile {profile!r} refuses the legacy/weaker "
            "execution path; missing required configuration: "
            + ", ".join(missing)
        )

    # ToolSpec signing is an offline act. A runtime holding the HMAC key could
    # author any bundle it accepts, so under a strict profile its presence in
    # any role is a refusal, not a configuration choice.
    if _configured("REMORA_TOOLSPEC_SIGNING_KEY"):
        raise RuntimeProfileError(
            f"REMORA runtime profile {profile!r} refuses a runtime that holds "
            "REMORA_TOOLSPEC_SIGNING_KEY: ToolSpec bundles are signed offline "
            "with Ed25519 and verified here with REMORA_TOOLSPEC_VERIFY_KEYS"
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
        from remora.profiles import deployment_environment

        if deployment_environment() != "production":
            raise RuntimeProfileError(
                "REMORA runtime profile 'controlled_pilot' requires "
                "REMORA_ENV=production"
            )

    _check_contract(profile)
    return profile


#: Where the BindingPolicy is read from (CR-006, A2).
ENV_BINDING_POLICY = "REMORA_BINDING_POLICY"


def _check_contract(profile: str) -> None:
    """Contract-version prerequisites, after the v1 ones above passed.

    v2 requires a BindingPolicy in which every binding is explicit, and refuses
    to start while any REQUIRED binding lacks its comparator. The accepted
    contract, policy digest and declared UNVERIFIABLE bindings are recorded
    as startup evidence.
    """
    from remora.observability.events import governance_event
    from remora.profiles import runtime_profile_contract

    contract = runtime_profile_contract()
    if not contract.endswith("/v2"):
        governance_event(
            "runtime_profile.legacy_contract", level=logging.WARNING,
            profile=profile, contract=contract)
        return
    _check_signature_format_v2(contract)
    policy = load_strict_binding_policy(contract)
    governance_event(
        "binding_policy.accepted", profile=profile, contract=contract,
        binding_policy_hash=policy.digest,
        unverifiable_bindings=",".join(policy.unverifiable()),
        not_applicable_resolved_effect=",".join(policy.not_applicable_tools("resolved_effect")))


def _check_signature_format_v2(contract: str) -> None:
    """CR-011: a v2 contract issues and accepts only signature format v2.

    Leases v2 are Ed25519 with no symmetric form, so the authority must hold
    the lease seed; the execution and effect domains already hold the public
    key (custody). ``REMORA_SIGNATURE_FORMAT`` may not ask for v1 here.
    """
    from remora.crypto.formats import ENV_SIGNATURE_FORMAT
    from remora.enforcement.custody import DOMAIN_AUTHORITY, domain_role

    requested = os.getenv(ENV_SIGNATURE_FORMAT, "").strip().lower()
    if requested and requested != "v2":
        raise RuntimeProfileError(
            f"contract {contract} issues signature format v2 only; "
            f"{ENV_SIGNATURE_FORMAT}={requested!r} is refused")
    if (domain_role(strict=False) == DOMAIN_AUTHORITY
            and not _configured("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE")):
        raise RuntimeProfileError(
            f"contract {contract} signs leases in format v2 (Ed25519, "
            "REMORA/EXECUTION-LEASE/v2) and has no symmetric form: the authority "
            "requires REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE")


def load_strict_binding_policy(contract: str) -> Any:
    """Load REMORA_BINDING_POLICY and check every REQUIRED comparator exists."""
    from remora.enforcement.binding_policy import BindingPolicyError, load_binding_policy

    path = os.getenv(ENV_BINDING_POLICY, "").strip()
    if not path:
        raise RuntimeProfileError(
            f"contract {contract} requires {ENV_BINDING_POLICY}: a BindingPolicy "
            "stating every binding as REQUIRED, NOT_APPLICABLE or UNVERIFIABLE")
    try:
        policy = load_binding_policy(path)
    except (BindingPolicyError, OSError) as exc:
        raise RuntimeProfileError(f"contract {contract}: {exc}") from exc

    problems: list[str] = []
    if policy.required("capability_set") and not _configured("REMORA_CAPABILITY_POLICY_FILE"):
        problems.append("capability_set is REQUIRED but REMORA_CAPABILITY_POLICY_FILE is not set")
    if policy.required("resolved_effect") and not _configured("REMORA_EFFECT_REGISTRY_MODULE"):
        problems.append(
            "resolved_effect is REQUIRED but REMORA_EFFECT_REGISTRY_MODULE is not set; a "
            "missing resolver is not NOT_APPLICABLE")
    if policy.required("runtime_surface") and not _configured("REMORA_TOOLSPEC_BUNDLE"):
        problems.append("runtime_surface is REQUIRED but no signed ToolSpec bundle is configured")

    # NOT_APPLICABLE exemptions must point at tools the signed bundle declares
    # read-only. Unknown or unrecognised action types never qualify.
    if policy.not_applicable_tools("resolved_effect"):
        from remora.execution.authorization import load_toolspec_bundle
        from remora.policy.decision_engine import _READ_ONLY_ACTION_TYPES
        from remora.toolcall.toolspec import ToolSpecRefused

        try:
            bundle = load_toolspec_bundle(os.environ)
        except (ToolSpecRefused, OSError, ValueError) as exc:
            problems.append(f"the signed bundle needed to check exemptions did not load: {exc}")
            bundle = None
        if bundle is not None:
            actions = {s.tool_id: s.action_type for s in bundle.tool_specs()}
            problems.extend(policy.check_read_only_exemptions(actions, _READ_ONLY_ACTION_TYPES))
    if policy.required("effect_mediation"):
        problems.extend(_effect_mediation_problems(policy))
    if problems:
        raise RuntimeProfileError(
            f"contract {contract} refuses to start: " + "; ".join(problems))
    return policy


def _effect_mediation_problems(policy: Any) -> list[str]:
    """CR-005: privileged tools are mediated, and tool code holds no credential."""
    from remora.enforcement.custody import DOMAIN_EXECUTOR, domain_role, effect_domain_split
    from remora.execution.authorization import load_toolspec_bundle
    from remora.execution.effect_policy import static_effect_policy_refusal
    from remora.toolcall.toolspec import ToolSpecRefused

    problems: list[str] = []
    try:
        role = domain_role(strict=False)
    except Exception:  # noqa: BLE001 - custody reports a bad role itself, later
        role = ""
    if role == DOMAIN_EXECUTOR and not effect_domain_split():
        problems.append(
            "effect_mediation is REQUIRED, so the tool execution domain may hold no "
            "direct effect credential; set REMORA_EFFECT_ENDPOINT to the effect domain "
            "that holds them")
    try:
        bundle = load_toolspec_bundle(os.environ)
    except (ToolSpecRefused, OSError, ValueError) as exc:
        return problems + [f"the signed bundle did not load: {exc}"]
    if bundle is None:
        return problems + ["effect_mediation is REQUIRED but no signed bundle is configured"]
    mediated = False
    for spec in bundle.tool_specs():
        refusal = static_effect_policy_refusal(spec)
        if refusal is not None:
            problems.append(f"{spec.tool_id}: {refusal}")
        mediated = mediated or spec.effect_mode == "MEDIATED"
    if mediated and not policy.required("capability_set"):
        problems.append(
            "a MEDIATED tool derives its effect authority from a capability set, so "
            "capability_set must be REQUIRED, not UNVERIFIABLE")
    return problems
