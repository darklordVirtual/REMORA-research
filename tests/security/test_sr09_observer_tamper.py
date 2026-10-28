"""SR-09 / SR-16 / SEC-09: the effect observer's record must be unreachable
from the observed code, and the observed process gets an allowlisted
environment.

Reproduced in the 2026-10 review: the harness kept ``records``, ``phase`` and
the hook as ``__main__`` globals in the same interpreter as the tool, and
trusted the last ``@@OBSERVATION@@`` marker in stdout. A tool could clear the
record list or print a forged clean marker and ``os._exit(0)``, and report a
clean run with no effects. The child also inherited the full parent
environment (signing keys, DSNs, PYTHONPATH) and the parent cwd.

Every PoC below must yield blinding or the observed effect — never a clean
run with the effect missing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from remora.toolcall.effect_observation import observe

TOOLS = Path(__file__).resolve().parents[1] / "fixtures" / "effect_tools"


def _interpreter_can_import_under_a_hook() -> str:
    code = ("import sys; sys.addaudithook(lambda e, a: None); "
            f"sys.path.insert(0, {str(TOOLS)!r}); import tools")
    proc = subprocess.run([sys.executable, "-B", "-c", code],
                          capture_output=True, text=True)
    return "" if proc.returncode == 0 else (proc.stderr.strip().splitlines() or ["?"])[-1]


_BROKEN = _interpreter_can_import_under_a_hook()
pytestmark = pytest.mark.skipif(
    bool(_BROKEN), reason=f"this interpreter cannot import under an audit hook: {_BROKEN}")


def _run(function: str, *cases, module: str = "tamper_tools", timeout_s: float = 60.0):
    return observe(module, function, list(cases), path=[str(TOOLS)], timeout_s=timeout_s)


def test_cleared_records_cannot_hide_the_write(tmp_path: Path) -> None:
    """PoC 1: __main__.records.clear() must not make a write vanish."""
    (case,) = _run("clears_observer_records", {"dir": str(tmp_path)}).cases
    assert "fs.write" in case.effect_classes, (
        "the write left no record: the observer's channel is reachable from "
        "the observed code"
    )


def test_forged_marker_plus_os_exit_is_blinding_not_clean(tmp_path: Path) -> None:
    """PoC 2: a forged @@OBSERVATION@@ marker and os._exit(0) must blind the
    case, never report it clean."""
    (case,) = _run("forges_clean_marker_and_exits", {}).cases
    assert case.blinded, "a forged marker with os._exit(0) produced a clean case"
    assert case.effect_classes == frozenset()


def test_json_dumps_replacement_is_tampering(tmp_path: Path) -> None:
    (case,) = _run("patches_json_dumps", {}).cases
    assert case.blinded
    assert any(cls == "observer_tampering" for cls, _ in case.blinding)


def test_stdout_replacement_is_tampering() -> None:
    (case,) = _run("replaces_stdout", {}).cases
    assert case.blinded
    assert any(cls == "observer_tampering" for cls, _ in case.blinding)


def test_dup2_is_tampering() -> None:
    (case,) = _run("dup2_stderr_onto_stdout", {}).cases
    assert case.blinded
    assert any(cls == "observer_tampering" for cls, _ in case.blinding)


def test_parent_env_secret_is_not_inherited(monkeypatch: pytest.MonkeyPatch) -> None:
    """SR-16: the child gets an allowlisted environment, not the parent's."""
    monkeypatch.setenv("SR16_SENTINEL", "signing-key-material")
    (case,) = _run("reads_sentinel_env", {}).cases
    # The fixture raises RuntimeError when the sentinel is visible; a raised
    # case here means the secret leaked into the observed child.
    assert case.raised == "", (
        f"parent environment leaked into the observed child: {case.raised}"
    )


def test_pythonpath_is_not_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SR-16: -I means a poisoned PYTHONPATH directory is not importable."""
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "poison_mod.py").write_text("MARKER = 'imported'\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(poison))

    (case,) = _run("imports_only_via_pythonpath", {"module": "poison_mod"}).cases
    assert "ModuleNotFoundError" in case.raised or "ImportError" in case.raised, (
        "the observed child imported a module from PYTHONPATH (no -I)"
    )
