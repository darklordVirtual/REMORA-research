# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Risk metadata a deployment declares for its own tools.

``servers/execution_api.py::TOOL_REGISTRY`` classifies six tool names. Every
other name — including every tool a product registers through
``REMORA_TOOL_REGISTRY_MODULE`` — fell through to
``{"risk_tier": "critical", "domain": "unknown", "action_type": "unknown"}``.

Failing closed on an unknown tool is right. The problem was that a deployment
had no way to make its tools *known*: a read-only sensor query and a
production valve write were both critical/unknown, so ACCEPT was structurally
unreachable for anything a deployment named itself. The OT pilot's battery
records the consequence — even ``read_sensor`` is written to expect
``verify_or_abstain``, never ``accept``.

This module lets a deployment declare that metadata, under four constraints
that keep the declaration from becoming a way to grant yourself anything:

1. **Additive only.** A name already in ``TOOL_REGISTRY`` may not be
   redeclared. Otherwise a deployment file could reclassify
   ``delete_production_database`` as ``low``/``read``.
2. **Closed vocabulary.** ``risk_tier`` and ``action_type`` are validated
   against the policy engine's own sets. A typo is a startup failure, not a
   tool that silently routes as unknown — and ``action_type`` is checked
   against the engine's *recognized* vocabulary, because an unrecognized
   value is floored to VERIFY and would look like a policy decision rather
   than a configuration error.
3. **Hashed.** ``_tool_registry_component_hash`` folds this file's digest in,
   so editing it moves the policy bundle hash, which invalidates every
   outstanding lease. A deployment cannot relabel a tool and keep executing
   under authorizations issued before the relabel.
4. **Downgrade-only stays downgrade-only.** ``schema_valid`` and
   ``rollback_available`` are declarations that can lower trust, never raise
   it; they are carried through the same ``_downgrade_only_bool`` path as
   before and are not special-cased here.

The file is JSON, not YAML, so the ``[api]`` extra needs no new dependency.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "DeploymentRegistryError",
    "KNOWN_ACTION_TYPES",
    "KNOWN_RISK_TIERS",
    "deployment_registry_digest",
    "load_deployment_tool_metadata",
    "reset_deployment_tool_metadata",
    "resolve_tool_metadata",
]

#: Path to the deployment's declaration. Empty/unset means no declaration,
#: which is the pre-existing behaviour exactly.
ENV_VAR = "REMORA_TOOL_METADATA_FILE"

#: Mirrors ``remora.policy.decision_engine._KNOWN_RISK_TIERS``. Imported
#: lazily below rather than duplicated as a literal, so the two cannot drift.
KNOWN_RISK_TIERS: frozenset[str] = frozenset({"low", "medium", "high", "critical"})

#: The union of every action-type set the engine recognizes. A value outside
#: it is floored to VERIFY by the engine ("unknown must mean not authorized"),
#: so accepting one here would turn a configuration mistake into a permanent
#: VERIFY that looks like policy.
KNOWN_ACTION_TYPES: frozenset[str] = frozenset()  # populated by _load_vocabulary()

_ALLOWED_KEYS = frozenset({
    "risk_tier", "domain", "action_type",
    "target_environment", "rollback_available", "schema_valid",
})
_REQUIRED_KEYS = frozenset({"risk_tier", "domain", "action_type"})

_SUPPORTED_VERSIONS = frozenset({1})


class DeploymentRegistryError(RuntimeError):
    """The deployment's tool metadata cannot be trusted, so it is not used.

    Always fatal at startup. A partially-loaded risk classification is worse
    than none: the tools that failed to parse would silently keep the
    critical/unknown floor while their neighbours moved, and nothing in the
    audit record would say which half was in force.
    """


def _load_vocabulary() -> tuple[frozenset[str], frozenset[str]]:
    """Read the engine's own action-type and risk-tier sets.

    Deliberately imported from ``remora.policy.decision_engine`` rather than
    restated: these sets change when policy changes, and a copy here would
    start accepting values the engine no longer recognizes.
    """
    from remora.policy.decision_engine import (
        _KNOWN_RISK_TIERS,
        _MUTATING_TYPES,
        _NON_ACTUATING_TYPES,
        _READ_ONLY_ACTION_TYPES,
        _READ_ONLY_TYPES,
    )

    actions = (
        _READ_ONLY_TYPES
        | _READ_ONLY_ACTION_TYPES
        | _MUTATING_TYPES
        | _NON_ACTUATING_TYPES
    )
    return frozenset(actions), frozenset(_KNOWN_RISK_TIERS)


def _validate_entry(tool: str, entry: Any) -> dict[str, Any]:
    actions, tiers = _load_vocabulary()

    if not isinstance(entry, Mapping):
        raise DeploymentRegistryError(
            f"{ENV_VAR}: tool {tool!r} must map to an object, got "
            f"{type(entry).__name__}"
        )
    keys = set(entry)
    if unknown := keys - _ALLOWED_KEYS:
        raise DeploymentRegistryError(
            f"{ENV_VAR}: tool {tool!r} declares unknown field(s) "
            f"{sorted(unknown)}; allowed: {sorted(_ALLOWED_KEYS)}"
        )
    if missing := _REQUIRED_KEYS - keys:
        raise DeploymentRegistryError(
            f"{ENV_VAR}: tool {tool!r} is missing required field(s) "
            f"{sorted(missing)}"
        )

    tier = str(entry["risk_tier"]).strip().lower()
    if tier not in tiers:
        raise DeploymentRegistryError(
            f"{ENV_VAR}: tool {tool!r} declares risk_tier {entry['risk_tier']!r}, "
            f"which the policy engine does not recognize; allowed: {sorted(tiers)}"
        )

    action = str(entry["action_type"]).strip().lower()
    if action not in actions:
        raise DeploymentRegistryError(
            f"{ENV_VAR}: tool {tool!r} declares action_type "
            f"{entry['action_type']!r}, which the policy engine does not "
            f"recognize. An unrecognized action type is floored to VERIFY, so "
            f"this would look like a policy decision rather than a typo. "
            f"Allowed: {sorted(actions)}"
        )

    domain = str(entry["domain"]).strip()
    if not domain:
        raise DeploymentRegistryError(
            f"{ENV_VAR}: tool {tool!r} declares an empty domain"
        )

    resolved: dict[str, Any] = {
        "risk_tier": tier, "domain": domain, "action_type": action,
    }
    if "target_environment" in entry:
        env = str(entry["target_environment"]).strip().lower()
        if not env:
            raise DeploymentRegistryError(
                f"{ENV_VAR}: tool {tool!r} declares an empty target_environment"
            )
        resolved["target_environment"] = env
    for flag in ("rollback_available", "schema_valid"):
        if flag in entry:
            if not isinstance(entry[flag], bool):
                raise DeploymentRegistryError(
                    f"{ENV_VAR}: tool {tool!r} field {flag} must be a boolean, "
                    f"got {type(entry[flag]).__name__}"
                )
            resolved[flag] = entry[flag]
    return resolved


def load_deployment_tool_metadata(
    path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse and validate the declaration. ``{}`` when none is configured.

    Raises ``DeploymentRegistryError`` on anything it cannot fully trust.
    """
    raw_path = str(path) if path is not None else os.getenv(ENV_VAR, "").strip()
    if not raw_path:
        return {}

    file = Path(raw_path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeploymentRegistryError(
            f"{ENV_VAR}={raw_path}: cannot read the declared tool metadata "
            f"({exc.strerror or exc})"
        ) from exc

    try:
        document = json.loads(text)
    except ValueError as exc:
        raise DeploymentRegistryError(
            f"{ENV_VAR}={raw_path}: not valid JSON ({exc})"
        ) from exc

    if not isinstance(document, Mapping):
        raise DeploymentRegistryError(
            f"{ENV_VAR}={raw_path}: top level must be an object"
        )
    version = document.get("version")
    if version not in _SUPPORTED_VERSIONS:
        raise DeploymentRegistryError(
            f"{ENV_VAR}={raw_path}: unsupported version {version!r}; "
            f"this build understands {sorted(_SUPPORTED_VERSIONS)}"
        )
    tools = document.get("tools")
    if not isinstance(tools, Mapping):
        raise DeploymentRegistryError(
            f"{ENV_VAR}={raw_path}: 'tools' must be an object mapping tool "
            f"name to metadata"
        )

    # Additive only. Resolved here rather than at lookup time so the refusal
    # happens at startup, where an operator sees it, instead of silently
    # losing to the core entry on some later request.
    from servers.execution_api import TOOL_REGISTRY

    resolved: dict[str, dict[str, Any]] = {}
    for tool, entry in tools.items():
        name = str(tool).strip()
        if not name:
            raise DeploymentRegistryError(
                f"{ENV_VAR}={raw_path}: empty tool name")
        if name in TOOL_REGISTRY:
            raise DeploymentRegistryError(
                f"{ENV_VAR}={raw_path}: tool {name!r} is already classified by "
                f"REMORA and may not be redeclared. A deployment can name its "
                f"own tools; it can never reclassify one the core classified."
            )
        resolved[name] = _validate_entry(name, entry)
    return resolved


_CACHE: dict[str, dict[str, Any]] | None = None
_CACHE_KEY: str | None = None


def _cached() -> dict[str, dict[str, Any]]:
    global _CACHE, _CACHE_KEY
    key = os.getenv(ENV_VAR, "").strip()
    if _CACHE is None or _CACHE_KEY != key:
        _CACHE = load_deployment_tool_metadata()
        _CACHE_KEY = key
    return _CACHE


def reset_deployment_tool_metadata() -> None:
    """Test hook: drop the cached declaration after changing the env."""
    global _CACHE, _CACHE_KEY
    _CACHE = None
    _CACHE_KEY = None


def resolve_tool_metadata(tool_name: str) -> tuple[dict[str, Any], bool]:
    """Return ``(metadata, declared)`` for one tool.

    ``declared`` is False only when neither REMORA nor the deployment has
    classified the name — the fail-closed critical/unknown case, unchanged.
    Callers use the flag where the old code tested ``in TOOL_REGISTRY``.
    """
    from servers.execution_api import TOOL_REGISTRY

    if (core := TOOL_REGISTRY.get(tool_name)) is not None:
        return dict(core), True
    if (declared := _cached().get(tool_name)) is not None:
        return dict(declared), True
    return {
        "risk_tier": "critical", "domain": "unknown", "action_type": "unknown",
    }, False


def deployment_registry_digest() -> str:
    """Identity of the declaration, for the policy bundle hash.

    Hashes the declaration's *resolved* content, not the file bytes: two files
    differing only in whitespace or key order describe the same policy and must
    not produce different lease-invalidating hashes. A file that fails to load
    hashes as an explicit marker — it must move the hash, never vanish from it.
    """
    spec = os.getenv(ENV_VAR, "").strip()
    if not spec:
        return "none"
    try:
        resolved = load_deployment_tool_metadata()
    except DeploymentRegistryError:
        return "unloadable"
    canonical = json.dumps(resolved, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Populate the exported vocabulary lazily on first import of the engine, but
# keep the module importable without it (the SDK-only install has no policy
# engine on some paths). Failure here is not fatal: _validate_entry loads the
# real sets itself and is the only thing that gates a declaration.
try:  # pragma: no cover - trivial best-effort export
    KNOWN_ACTION_TYPES, KNOWN_RISK_TIERS = _load_vocabulary()
except Exception:  # noqa: BLE001 - optional convenience export only
    pass
