# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every result generator imports only names that exist in this repository.

experiments/chi_perturbation_study.py imported two helpers that never existed
here (they stayed behind when the repository was extracted), so it could not
start from the first commit until 2026-09-28. Nothing noticed, because nothing
ran it. This test reads each generator named in the results manifest and
checks every ``from experiments|remora|scripts... import name`` against the
module it names, without running the generator.
"""
from __future__ import annotations

import ast
import importlib
import shlex
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "assurance" / "results_manifest_v1.yaml"
LOCAL = ("experiments", "remora", "scripts")


def _generators() -> list[str]:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    scripts = set()
    for entry in data["results"]:
        gen = entry.get("generator")
        if gen:
            parts = shlex.split(gen)
            if len(parts) > 1 and parts[1].endswith(".py"):
                scripts.add(parts[1])
    return sorted(scripts)


def _local_imports(path: Path) -> list[tuple[str, str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] in LOCAL:
                out += [(node.module, alias.name, node.lineno) for alias in node.names if alias.name != "*"]
    return out


@pytest.mark.parametrize("script", _generators())
def test_generator_imports_resolve(script: str) -> None:
    path = ROOT / script
    assert path.exists(), f"manifest names a generator that does not exist: {script}"
    sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
    missing = []
    unimportable = []
    try:
        for module, name, line in _local_imports(path):
            try:
                mod = importlib.import_module(module)
            except ModuleNotFoundError as exc:
                if (exc.name or "").split(".")[0] in LOCAL:
                    missing.append(f"{script}:{line}: module {module} does not exist")
                else:
                    # Keep checking the other imports; skip only at the end.
                    unimportable.append(f"{module} needs {exc.name}")
                continue
            if not hasattr(mod, name):
                try:
                    importlib.import_module(f"{module}.{name}")
                except ModuleNotFoundError:
                    missing.append(f"{script}:{line}: {module} has no {name}")
    finally:
        del sys.path[:2]
    assert missing == []
    if unimportable:
        pytest.skip("; ".join(unimportable) + ", not installed here")
