# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-014: the runtime wheel carries no benchmark datasets.

Three generated modules under ``remora/benchmarks`` hold 1.5 MB of inline
benchmark items. They were shipped in the runtime wheel, where they enlarge
what a reviewer has to treat as code. Nothing at runtime imports them. They
are now excluded from the wheel (``[tool.hatch.build.targets.wheel] exclude``)
and stay in the source tree for research use. The CI wheel job inspects the
built wheel itself; this suite checks the declaration and keeps it honest.
"""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = {
    "remora/benchmarks/extended_v2.py",
    "remora/benchmarks/extended_v2_n500.py",
    "remora/benchmarks/sap_v3_n1200.py",
}
#: A module this large under the runtime packages is data, not code, unless
#: it is named here with a reason.
MAX_RUNTIME_MODULE_BYTES = 300_000


def _excluded() -> set[str]:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        config = tomllib.load(fh)
    return set(config["tool"]["hatch"]["build"]["targets"]["wheel"].get("exclude", []))


def test_the_datasets_are_excluded_from_the_wheel() -> None:
    assert DATASETS <= _excluded()


def test_the_exclusions_name_files_that_exist() -> None:
    """An exclusion that matches nothing excludes nothing."""
    for path in _excluded():
        assert (ROOT / path).is_file(), path


def _runtime_modules():
    for package in ("remora", "servers"):
        for path in (ROOT / package).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if "__pycache__" not in rel and rel not in _excluded():
                yield rel, path


def test_no_shipped_module_imports_an_excluded_dataset() -> None:
    """Otherwise the wheel would ship an import that cannot resolve."""
    names = {p[:-3].replace("/", ".") for p in _excluded()}
    offenders = []
    for rel, path in _runtime_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = {node.module} | {f"{node.module}.{a.name}" for a in node.names}
            elif isinstance(node, ast.Import):
                imported = {a.name for a in node.names}
            else:
                continue
            if imported & names:
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


def test_no_other_shipped_module_is_dataset_sized() -> None:
    large = [rel for rel, path in _runtime_modules()
             if path.stat().st_size > MAX_RUNTIME_MODULE_BYTES]
    assert large == [], (
        f"{large} exceed {MAX_RUNTIME_MODULE_BYTES} bytes: move data out of the runtime "
        "packages or exclude it from the wheel")
