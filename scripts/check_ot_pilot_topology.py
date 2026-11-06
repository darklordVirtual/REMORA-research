#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Drift check of the OT pilot's credential and network topology (AACP E).

Reads ``deploy/ot-pilot/credential_topology.yaml`` and checks it against
``deploy/ot-pilot/docker-compose.yml`` and the pilot's Python. It fails on:

1. a credential the compose file hands to a service, or a secret-like variable
   the pilot's code reads, that the register does not declare;
2. a register entry that no service carries any more;
3. a holder set or reader set that differs from what the files say;
4. a credential declared unreachable that the agent service carries, an
   ``env_file`` on any service, a privilege or namespace setting, or an agent
   service with keys or mounts outside its declared shape;
5. a network whose declared membership or ``internal`` flag differs from the
   compose file, an agent zone that is not exactly its declared networks, or
   an agent network shared with a protected service.

It does not read secret values, contact a deployment or establish that the
running stack matches the file; the boundary run does that part.

    python scripts/check_ot_pilot_topology.py [--json]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "deploy" / "ot-pilot"
REGISTER = PILOT / "credential_topology.yaml"
COMPOSE = PILOT / "docker-compose.yml"

_SECRET_NAME = re.compile(r"TOKEN|KEY|SEED|SECRET|PASSWORD|DSN|FAULTS")
#: The agent service's whole declared shape.
_AGENT_KEYS = frozenset({"image", "pull_policy", "profiles", "command", "environment",
                         "networks"})
#: Settings that widen what a container can reach, on any service.
_ESCALATING_KEYS = frozenset({"privileged", "pid", "ipc", "network_mode", "cap_add",
                              "devices", "userns_mode", "security_opt"})
_REFERENCE = re.compile(r"\$\{(\w+)")


def compose_holders(compose: dict[str, Any], register: dict[str, Any]) -> dict[str, set[str]]:
    """Credential -> services carrying it, from ``${VAR}`` references and literals."""
    literal_names: dict[str, str] = {}
    for entry in register.get("credentials", []):
        for env_name in entry.get("literal_in", []) or []:
            literal_names[env_name] = entry["name"]
    holders: dict[str, set[str]] = {}
    for service, spec in (compose.get("services") or {}).items():
        env = spec.get("environment") or {}
        if isinstance(env, list):
            env = dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
        for key, value in env.items():
            refs = _REFERENCE.findall(str(value))
            for ref in refs:
                holders.setdefault(ref, set()).add(service)
            if not refs and key in literal_names:
                holders.setdefault(literal_names[key], set()).add(service)
            elif not refs and _SECRET_NAME.search(key):
                holders.setdefault(f"<undeclared literal {key}>", set()).add(service)
    return holders


def code_readers(names: set[str]) -> dict[str, set[str]]:
    """Variable -> pilot modules reading it (os.environ / os.getenv, static keys)."""
    readers: dict[str, set[str]] = {}
    for path in sorted(PILOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            key = None
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                target = node.func
                base = ast.unparse(target.value)
                if (target.attr == "get" and base == "os.environ") or \
                        (target.attr == "getenv" and base == "os"):
                    if node.args and isinstance(node.args[0], ast.Constant):
                        key = node.args[0].value
            elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                if isinstance(node.slice, ast.Constant):
                    key = node.slice.value
            if isinstance(key, str) and (key in names or _SECRET_NAME.search(key)):
                readers.setdefault(key, set()).add(rel)
    return readers


def check() -> tuple[list[str], dict[str, Any]]:
    register = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    problems: list[str] = []
    declared = {e["name"]: e for e in register.get("credentials", [])}
    holders = compose_holders(compose, register)
    readers = code_readers(set(declared))

    for name, services in sorted(holders.items()):
        if name not in declared:
            problems.append(f"undeclared credential {name} carried by {sorted(services)}")
    for name, entry in declared.items():
        found = holders.get(name, set())
        if not found:
            problems.append(f"stale entry {name}: no service carries it")
        elif set(entry.get("holders", [])) != found:
            problems.append(f"{name}: holders {sorted(entry.get('holders', []))} "
                            f"!= compose {sorted(found)}")
        if set(entry.get("read_by", []) or []) != readers.get(name, set()):
            problems.append(f"{name}: read_by {sorted(entry.get('read_by', []) or [])} "
                            f"!= code {sorted(readers.get(name, set()))}")
    for name, mods in sorted(readers.items()):
        if name not in declared and _SECRET_NAME.search(name):
            problems.append(f"undeclared secret-like read {name} in {sorted(mods)}")

    zone = register["agent_zone"]
    agent = zone["service"]
    services = compose.get("services") or {}
    # Ways to hand a container secrets or reach that the environment scan above
    # cannot see (adversarial review 2026-11-06): an env_file anywhere, and on
    # the agent any key outside the declared shape, a host mount, or a
    # privilege, namespace or device setting.
    for service, spec in services.items():
        if "env_file" in (spec or {}):
            problems.append(f"service {service} uses env_file, which this check cannot read")
        for key in _ESCALATING_KEYS & set(spec or {}):
            problems.append(f"service {service} sets {key}")
    agent_spec = services.get(agent) or {}
    extra = set(agent_spec) - _AGENT_KEYS
    if extra:
        problems.append(f"agent zone service sets undeclared keys {sorted(extra)}")
    for volume in agent_spec.get("volumes") or []:
        problems.append(f"agent zone mounts {volume!r}; it is declared to mount nothing")
    if agent not in services:
        problems.append(f"agent zone service {agent!r} is not in the compose file")
    for name, entry in declared.items():
        if not entry.get("agent_reachable") and agent in holders.get(name, set()):
            problems.append(f"{name} is declared unreachable and the agent service carries it")

    declared_nets = register.get("networks", {})
    compose_nets = compose.get("networks") or {}
    members: dict[str, set[str]] = {}
    for service, spec in services.items():
        for net in spec.get("networks") or ["default"]:
            members.setdefault(net, set()).add(service)
    for net, spec in declared_nets.items():
        if net not in compose_nets:
            problems.append(f"network {net} is declared and not in the compose file")
            continue
        if bool((compose_nets.get(net) or {}).get("internal", False)) != bool(spec["internal"]):
            problems.append(f"network {net}: internal flag differs from the compose file")
        if set(spec["members"]) != members.get(net, set()):
            problems.append(f"network {net}: members {sorted(spec['members'])} != compose "
                            f"{sorted(members.get(net, set()))}")
    for net in compose_nets:
        if net not in declared_nets:
            problems.append(f"undeclared network {net}")
    agent_nets = set((services.get(agent) or {}).get("networks") or ["default"])
    if agent_nets != set(zone["networks"]):
        problems.append(f"agent zone networks {sorted(agent_nets)} != declared "
                        f"{sorted(zone['networks'])}")
    for net in agent_nets:
        shared = members.get(net, set()) & set(register.get("protected_services", {}))
        if shared:
            problems.append(f"agent network {net} is shared with protected {sorted(shared)}")
        if not (compose_nets.get(net) or {}).get("internal", False):
            problems.append(f"agent network {net} is not internal")

    summary = {
        "register": REGISTER.relative_to(ROOT).as_posix(),
        "compose": COMPOSE.relative_to(ROOT).as_posix(),
        "credentials": len(declared),
        "holders": {k: sorted(v) for k, v in sorted(holders.items())},
        "readers": {k: sorted(v) for k, v in sorted(readers.items())},
        "agent_zone": {"service": agent, "networks": sorted(agent_nets),
                       "credentials_carried": sorted(n for n, s in holders.items()
                                                     if agent in s)},
        "network_members": {k: sorted(v) for k, v in sorted(members.items())},
        "problems": problems,
        "ok": not problems,
    }
    return problems, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OT pilot topology drift check")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)
    problems, summary = check()
    if args.json:
        print(json.dumps(summary, indent=1))
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if not problems:
        print(f"[PASS] OT pilot topology: {summary['credentials']} credentials, agent zone "
              f"{summary['agent_zone']['service']} on {summary['agent_zone']['networks']} "
              f"carries {summary['agent_zone']['credentials_carried']}",
              file=sys.stderr if args.json else sys.stdout)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
