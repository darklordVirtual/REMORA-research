"""The mutation sweep must run every test that exercises the modules it mutates.

mutmut measures test strength by asking whether the selected tests notice a
mutation. A test that would notice but is not in
``[tool.mutmut] pytest_add_cli_args_test_selection`` cannot kill anything, so
its mutants are reported as survivors. The reported number then describes the
selection, not the suite.

That is not hypothetical either. The sweep's install step had been broken since
the project was renamed to ``remora-assurance``, so no sweep ran for weeks while
the four mutated modules kept acquiring tests. The first sweep to execute again
reported 226 new survivors against the committed baseline. Twenty-one test
modules exercising those modules were absent from the selection.

Scope (declared, not exhaustive): this checks *import reachability* -- a test
module that imports one of the mutated modules, directly or via
``remora.enforcement``, must be in the selection. It cannot detect a test that
exercises the module only through a deeper transitive import, and it does not
claim the selection is sufficient, only that nothing obviously relevant is
missing.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"


def _mutmut_config() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return dict(tomllib.load(handle)["tool"]["mutmut"])


def _mutated_module_names() -> list[str]:
    """``remora/enforcement/lease.py`` -> ``lease``."""
    return [Path(path).stem for path in _mutmut_config()["only_mutate"]]


def _selected_test_files() -> set[str]:
    return {
        Path(entry).name
        for entry in _mutmut_config()["pytest_add_cli_args_test_selection"]
    }


def _importers(module_names: list[str]) -> set[str]:
    names = "|".join(re.escape(name) for name in module_names)
    pattern = re.compile(
        rf"(?:from remora\.enforcement\.(?:{names})\b"
        rf"|import remora\.enforcement\.(?:{names})\b"
        rf"|from remora\.enforcement import (?:[^\n]*\b(?:{names})\b))"
    )
    return {
        path.name
        for path in sorted(TESTS_DIR.glob("test_*.py"))
        if pattern.search(path.read_text(encoding="utf-8"))
    }


def test_every_test_touching_a_mutated_module_is_in_the_sweep() -> None:
    missing = sorted(_importers(_mutated_module_names()) - _selected_test_files())
    assert not missing, (
        "these test modules import a module the mutation sweep mutates but are not in "
        "[tool.mutmut] pytest_add_cli_args_test_selection, so their mutants are "
        f"reported as survivors without ever being given a chance to die: {missing}"
    )


def test_the_selection_only_names_tests_that_exist() -> None:
    absent = sorted(name for name in _selected_test_files() if not (TESTS_DIR / name).is_file())
    assert not absent, (
        f"the sweep selects test files that do not exist, so pytest would error: {absent}"
    )


def test_the_guard_would_notice_a_missing_file() -> None:
    """A guard that cannot fail is not a guard."""
    importers = _importers(_mutated_module_names())
    assert importers, "no test module imports the mutated modules -- the pattern is wrong"
    assert importers - {"test_execution_lease.py"} != importers, (
        "tests/test_execution_lease.py must be detected as an importer of a mutated "
        "module; if it was renamed, this guard's pattern needs the same update"
    )


def _deselected_node_ids() -> list[str]:
    args = _mutmut_config()["pytest_add_cli_args"]
    return [value for flag, value in zip(args, args[1:]) if flag == "--deselect"]


def test_every_deselected_node_id_still_exists() -> None:
    """A --deselect for a renamed test is a silent no-op that reds the sweep later."""
    import subprocess
    import sys

    missing = []
    for node_id in _deselected_node_ids():
        path, _, selector = node_id.partition("::")
        if not (REPO_ROOT / path).is_file():
            missing.append(f"{node_id} (file absent)")
            continue
        collected = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "pytest", node_id, "--collect-only", "-q", "--no-header"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if collected.returncode != 0 or selector not in collected.stdout:
            missing.append(node_id)
    assert not missing, (
        "the mutation sweep deselects node ids that no longer collect, so the tests it "
        f"meant to skip are not the tests it skips: {missing}"
    )


def test_the_deselections_are_confined_to_selected_modules() -> None:
    selected = _selected_test_files()
    stray = sorted(
        node_id
        for node_id in _deselected_node_ids()
        if Path(node_id.partition("::")[0]).name not in selected
    )
    assert not stray, (
        f"deselecting a test the sweep never runs is dead configuration: {stray}"
    )
