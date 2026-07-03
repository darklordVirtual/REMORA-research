"""CascadeEngine must never be on a tool-execution / authorization path.

External security audit CLAIM 2: FastGate can return ACCEPT from one oracle's
self-reported confidence with no policy/action metadata. That is acceptable
ONLY because the cascade is answer-quality-only and is not wired to any
enforcement surface. This test pins that invariant: the modules that gate real
tool execution must not import CascadeEngine.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Surfaces that can authorize or block a real tool call.
ENFORCEMENT_MODULES = [
    "remora/policy/decision_engine.py",
    "remora/enforcement/gate.py",
    "remora/enforcement/token.py",
    "remora/adapters/action_gate.py",
    "remora/adapters/gateway.py",
    "scripts/remora_hook.py",
    "servers/api.py",
]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names.add(f"{node.module}.{alias.name}")
            names.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


def test_enforcement_paths_do_not_import_cascade_engine():
    offenders = []
    for rel in ENFORCEMENT_MODULES:
        p = ROOT / rel
        if not p.exists():
            continue
        imports = _imports(p)
        if any("CascadeEngine" in name or name.endswith("cascade.engine")
               or name == "remora.cascade" for name in imports):
            offenders.append(rel)
    assert not offenders, (
        f"enforcement modules import CascadeEngine (execution-authorization "
        f"risk): {offenders}"
    )


def test_cascade_docstring_warns_not_authorization():
    src = (ROOT / "remora" / "cascade" / "engine.py").read_text(encoding="utf-8")
    assert "NOT an execution-authorization component" in src
