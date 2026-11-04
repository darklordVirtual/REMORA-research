#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Author and sign the OT pilot's ToolSpec bundle (RMR-CR-001, offline).

Run once after ``init_tokens.py``::

    python deploy/ot-pilot/build_toolspec.py           # writes toolspec-bundle.json, keeps the seed
    python deploy/ot-pilot/build_toolspec.py --force   # re-sign with a new seed

The six tools are described from the deployment's own sources: the callable
in ``ot_registry.py`` (its source span is the attested ``callable_digest``,
the same measurement the API performs at registration), the semantic
contract in ``ot_bundle.py``, and the risk declaration in
``tool_metadata.json``. The bundle is signed with an Ed25519 seed that stays
in ``.toolspec-seed`` (mode 600, never copied into the image); the runtime
receives only the public key and the pinned digest through ``.env``, so no
process on the stack can author a bundle.

Until this file existed the pilot ran with no ToolSpec: every call was
reported ``enforced=False`` and WS1 had no spec identity to bind to.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

BUNDLE_PATH = HERE / "toolspec-bundle.json"
SEED_PATH = HERE / ".toolspec-seed"
ENV_PATH = HERE / ".env"
#: The environments the pilot's tools may be called for. ``prod`` is the
#: pilot's declared footing; ``staging`` lets the battery name a non-production
#: target when a run is about the policy for that environment.
ALLOWED_TARGETS = ("prod", "staging")

ARGUMENTS: dict[str, dict[str, Any]] = {
    "read_sensor": {"sensor_id": {"type": "string"}},
    "adjust_setpoint": {"loop": {"type": "string"}, "value": {"type": "number"}},
    "set_valve_position": {"valve": {"type": "string"}, "position_pct": {"type": "number"}},
    "acknowledge_alarm": {"alarm_id": {"type": "string"}},
    "create_work_order": {"wo_id": {"type": "string"}, "title": {"type": "string"},
                          "description": {"type": "string"}},
    "close_work_order": {"wo_id": {"type": "string"}, "reason": {"type": "string"}},
}
REQUIRED: dict[str, list[str]] = {
    "read_sensor": ["sensor_id"], "adjust_setpoint": ["loop", "value"],
    "set_valve_position": ["valve", "position_pct"], "acknowledge_alarm": ["alarm_id"],
    "create_work_order": ["wo_id"], "close_work_order": ["wo_id"],
}
DESCRIPTIONS = {
    "read_sensor": "Read one sensor's current value and unit from the plant inventory.",
    "adjust_setpoint": "Move a control loop's setpoint on the plant (physical process change).",
    "set_valve_position": "Set a valve's position in percent on the plant (physical process change).",
    "acknowledge_alarm": "Acknowledge an active alarm so it no longer demands attention.",
    "create_work_order": "Create a maintenance work order that later authorises work.",
    "close_work_order": "Close a work order, ending the authority it carried.",
}


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def unsigned_bundle() -> dict[str, Any]:
    """The pilot's six specs before signing, from the deployment's own sources."""
    from remora.toolcall.callable_digest import source_digest

    registry = _module("ot_registry")
    bundle_mod = _module("ot_bundle")
    registry_contracts = bundle_mod.build_semantic_bundle().contracts.contracts
    values = registry_contracts.values() if isinstance(registry_contracts, dict) else registry_contracts
    contracts = {c.tool: c for c in values}
    metadata = json.loads((HERE / "tool_metadata.json").read_text(encoding="utf-8"))["tools"]
    specs = []
    for name, fn in sorted(registry.TOOLS.items() if hasattr(registry, "TOOLS") else
                           ((n, getattr(registry, n)) for n in ARGUMENTS)):
        contract = contracts[name]
        meta = metadata[name]
        description = DESCRIPTIONS[name]
        specs.append({
            "tool_id": name,
            "version": 1,
            "callable_digest": source_digest(fn),
            "implementation_identity": f"ot_registry.{name}@ot-pilot",
            "description": description,
            "description_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest(),
            "argument_schema": {"type": "object", "properties": ARGUMENTS[name],
                                "required": REQUIRED[name], "additionalProperties": False},
            "risk_tier": meta["risk_tier"],
            "action_type": meta["action_type"],
            "domain": meta["domain"],
            "capabilities": [contract.capability],
            "semantic_contract": {
                "capability": contract.capability, "effect": contract.effect,
                "resource_type": contract.resource_type, "mutation": contract.mutation,
                "argument_roles": dict(contract.argument_roles),
            },
            "credential_scope": [f"ot:{contract.capability}"],
            "allowed_targets": list(ALLOWED_TARGETS),
            "idempotency_contract": {"safe_to_retry": not contract.mutation,
                                     "key_derivation": "canonical_args"},
            "postcondition_reader": None,
            "compensation_tool": None,
            "timeout_policy": {"dispatch_timeout_seconds": 15},
            "network_policy": {"egress": "none"},
            "signing_identity": "unsigned",
        })
    return {"schema_version": 4, "tool_specs": specs}


def _write_private(path: Path, content: str, *, force: bool) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        if force:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    force = "--force" in (argv if argv is not None else sys.argv[1:])
    if BUNDLE_PATH.exists() and not force:
        print(f"{BUNDLE_PATH} already exists; use --force to re-sign with a new seed.",
              file=sys.stderr)
        return 1
    if not ENV_PATH.exists():
        print(f"{ENV_PATH} is missing; run deploy/ot-pilot/init_tokens.py first.", file=sys.stderr)
        return 1
    from remora.toolcall.toolspec_sign import sign_with_seed

    seed = secrets.token_hex(32)
    signed, public, digest = sign_with_seed(unsigned_bundle(), seed)
    _write_private(SEED_PATH, seed + "\n", force=True)
    BUNDLE_PATH.write_text(json.dumps(signed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [line for line in ENV_PATH.read_text(encoding="utf-8").splitlines()
             if not line.startswith(("OT_TOOLSPEC_VERIFY_KEY=", "OT_TOOLSPEC_PINNED_DIGEST="))]
    lines += [f"OT_TOOLSPEC_VERIFY_KEY={public}", f"OT_TOOLSPEC_PINNED_DIGEST={digest}", ""]
    _write_private(ENV_PATH, "\n".join(lines), force=True)
    print(f"wrote {BUNDLE_PATH.name} ({len(signed['tool_specs'])} tools), pinned digest {digest[:16]}…; "
          f"seed kept in {SEED_PATH.name} (mode 600), public key and digest appended to .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
