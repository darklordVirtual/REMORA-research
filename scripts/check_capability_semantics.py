#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Semantic capability-register validation against the runtime wiring.

Issue #84 residual 2: a structurally valid register must not be able to
claim a surface is wired when the corresponding runtime path is absent or
weaker. The freshness gate (#383) binds a capability to the CONTENT of its
evidence files; this gate binds the claimed STATUS to what the code can be
shown to do:

* ``WIRED_API_PATH`` (and above) — the capability must cite a live server
  module, and when it cites implementation modules under ``remora/``, at
  least one of them must be TRANSITIVELY IMPORTED from a public API surface
  (``servers/api.py`` / ``servers/execution_api.py``). A register entry
  whose implementation the API cannot even reach is an over-claim, however
  valid its YAML.
* ``PERSISTED_ATOMIC`` — additionally, at least one cited implementation
  module must carry a durable-backend path (``REMORA_PG_DSN`` /
  ``REMORA_CHAIN_DB`` / ``psycopg`` / ``sqlite3``): atomic persistence
  claimed by an entry whose code has no durable selector is a fiction.
* ``WIRED_REFERENCE_PATH`` — the reference flow must exist: at least one
  evidence file under ``scripts/`` or a demo/hook module.
* Every capability, at every level, must cite at least one test.

The import graph is a conservative static scan (``import``/``from`` lines
over ``remora/`` and ``servers/``): it can miss dynamic wiring, so a
failure here means "not demonstrably wired", and the fix is either real
wiring or an honest status — never a weaker check.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "capability_register_v1.yaml"
SURFACES = ("servers/api.py", "servers/execution_api.py")
DURABLE_TOKENS = ("REMORA_PG_DSN", "REMORA_CHAIN_DB", "psycopg", "sqlite3")

_IMPORT = re.compile(
    r"^\s*(?:from\s+([A-Za-z_][\w\.]*)\s+import|import\s+([A-Za-z_][\w\.]*))",
    re.MULTILINE,
)


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def build_import_graph() -> tuple[dict[str, set[str]], dict[str, str]]:
    """module -> imported modules (repo-internal only); module -> file."""
    modules: dict[str, Path] = {}
    for top in ("remora", "servers"):
        for py in (ROOT / top).rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            modules[_module_name(py)] = py
    known = sorted(modules, key=len, reverse=True)

    def resolve(name: str) -> str | None:
        if not (name.startswith("remora") or name.startswith("servers")):
            return None
        while name:
            if name in modules:
                return name
            name = name.rpartition(".")[0]
        return None

    graph: dict[str, set[str]] = {m: set() for m in modules}
    for mod, path in modules.items():
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in _IMPORT.finditer(text):
            target = resolve(m.group(1) or m.group(2))
            if target and target != mod:
                graph[mod].add(target)
    _ = known
    return graph, {m: str(p.relative_to(ROOT)).replace("\\", "/")
                   for m, p in modules.items()}


def reachable_from_surfaces(graph: dict[str, set[str]]) -> set[str]:
    seeds = [m for m, f in _FILES.items() if f in SURFACES]
    seen: set[str] = set()
    stack = list(seeds)
    while stack:
        mod = stack.pop()
        if mod in seen:
            continue
        seen.add(mod)
        stack.extend(graph.get(mod, ()))
    # A package module reached implies its __init__ ran; treat submodules of
    # reached packages conservatively as NOT reached — only explicit imports
    # count, which is the point of the check.
    return seen


_GRAPH, _FILES = build_import_graph()
_FILE_TO_MOD = {f: m for m, f in _FILES.items()}
_REACHED = reachable_from_surfaces(_GRAPH)
_LADDER = ["IMPLEMENTED_LIBRARY", "WIRED_REFERENCE_PATH", "WIRED_API_PATH",
           "PERSISTED_ATOMIC", "ENFORCED_PRODUCTION", "EXTERNALLY_VERIFIED"]


def check_capability(cap: dict) -> list[str]:
    cid, status = cap["id"], cap["status"]
    evidence = [str(e) for e in cap.get("evidence", [])]
    problems: list[str] = []
    level = _LADDER.index(status) if status in _LADDER else -1
    if level < 0:
        return [f"unknown status {status!r}"]

    if not any(e.startswith("tests/") for e in evidence):
        problems.append("no test evidence cited — untested at every level")

    if level >= _LADDER.index("WIRED_REFERENCE_PATH") and level < _LADDER.index("WIRED_API_PATH"):
        if not any(e.startswith("scripts/") or "demo" in e or "hook" in e
                   for e in evidence):
            problems.append(
                "WIRED_REFERENCE_PATH without any reference flow "
                "(scripts/ or demo/hook evidence)")

    if level >= _LADDER.index("WIRED_API_PATH"):
        servers_cited = [e for e in evidence if e.startswith("servers/")]
        if not servers_cited:
            problems.append(
                f"{status} without any server module in evidence — "
                "the API path is asserted, not shown")
        impl_mods = [_FILE_TO_MOD[e] for e in evidence
                     if e.startswith("remora/") and e in _FILE_TO_MOD]
        if impl_mods and not any(m in _REACHED for m in impl_mods):
            problems.append(
                f"{status} but no cited remora implementation module is "
                "transitively imported from a public API surface "
                f"({', '.join(SURFACES)}) — the register claims wiring "
                "the import graph cannot demonstrate")

    if level >= _LADDER.index("PERSISTED_ATOMIC"):
        # Only the remora implementation counts: server modules mention
        # storage backends for many reasons, and letting them satisfy the
        # durability claim would make the check vacuous.
        impl_files = [e for e in evidence if e.startswith("remora/")]
        durable = False
        for e in impl_files:
            p = ROOT / e
            if p.exists() and any(tok in p.read_text(encoding="utf-8",
                                                     errors="replace")
                                  for tok in DURABLE_TOKENS):
                durable = True
                break
        if not durable:
            problems.append(
                "PERSISTED_ATOMIC but no cited implementation carries a "
                f"durable-backend path ({'/'.join(DURABLE_TOKENS)})")

    return [f"{cid}: {p}" for p in problems]


def main() -> int:
    register = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    failures: list[str] = []
    for cap in register["capabilities"]:
        failures.extend(check_capability(cap))
    if failures:
        print(f"[FAIL] capability semantics: {len(failures)} over-claim(s):",
              file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("Fix: wire the capability for real, or record the honest "
              "weaker status — never weaken this check.", file=sys.stderr)
        return 1
    n = len(register["capabilities"])
    print(f"[PASS] capability semantics: {n} entries; every claimed status "
          f"is demonstrable in the runtime wiring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
