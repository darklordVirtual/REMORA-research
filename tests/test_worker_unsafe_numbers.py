# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-013: both Workers refuse numbers a JavaScript round trip would change.

The Workers parse request bodies into JavaScript numbers and serialise them
again before REMORA binds the call: 9007199254740993 arrived as
9007199254740992 and 1.0 as 1. Python binds and executes what arrives, so
nothing diverges after the binding, but the caller's value had already become
another one. The Workers now refuse such a body
(``workers/*/src/json_numbers.ts``).

This test runs agent-control's module under node (bundled with esbuild, as
the envelope parity test does) against what Python would bind, and checks the
two Workers carry the identical module. mcp-gateway's copy is also tested by
vitest (``workers/mcp-gateway/test/json_numbers.test.ts``).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT_CONTROL = ROOT / "workers" / "agent-control"
MODULES = [ROOT / "workers" / w / "src" / "json_numbers.ts" for w in ("agent-control", "mcp-gateway")]

LITERALS = [
    "9007199254740993", "-9007199254740993", "9007199254740991", "1.0", "-0.0", "1e2",
    "123456789012345678.0", "1e400", "0", "42", "1.5", "0.1", "2.50", "-3.25e-2", "1e21",
]


def test_both_workers_carry_the_same_module() -> None:
    first, second = (m.read_bytes() for m in MODULES)
    assert first == second


def _python_view(literal: str) -> str | None:
    """Would a JavaScript round trip hand Python a different value or type?"""
    value = json.loads(literal)
    if isinstance(value, int):
        return "unsafe_integer" if abs(value) > 2 ** 53 - 1 else None
    if value in (float("inf"), float("-inf")):
        return "non_finite"
    # JavaScript writes an integral double without a fraction or exponent
    # below 1e21, and Python reads that back as an int.
    return "float_becomes_integer" if value.is_integer() and abs(value) < 1e21 else None


@pytest.mark.parametrize("literal", LITERALS)
def test_the_python_reading_of_each_literal(literal) -> None:
    """The oracle the Worker is checked against, stated once."""
    assert _python_view(literal) in (None, "unsafe_integer", "float_becomes_integer", "non_finite")


def test_the_worker_refuses_exactly_what_python_would_receive_changed(tmp_path) -> None:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not (AGENT_CONTROL / "node_modules" / "esbuild").exists():
        pytest.skip("esbuild not installed in workers/agent-control")
    bundle = tmp_path / "json_numbers.mjs"
    subprocess.run(
        ["npx", "esbuild", str(MODULES[0]), "--bundle", "--format=esm", "--platform=node",
         f"--outfile={bundle}"],
        cwd=AGENT_CONTROL, check=True, capture_output=True, shell=os.name == "nt")
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        f"import {{ unsafeNumberReason, parseJsonStrict }} from {json.dumps(bundle.as_uri())};\n"
        f"const literals = {json.dumps(LITERALS)};\n"
        "const reasons = literals.map((l) => unsafeNumberReason(l));\n"
        "let nested = null;\n"
        "try { parseJsonStrict('{\"arguments\":{\"id\":9007199254740993}}'); }\n"
        "catch (e) { nested = e.reason; }\n"
        "console.log(JSON.stringify({ reasons, nested }));\n",
        encoding="utf-8")
    out = subprocess.run(["node", str(driver)], cwd=AGENT_CONTROL, check=True,
                         capture_output=True, text=True)
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["reasons"] == [_python_view(lit) for lit in LITERALS]
    assert result["nested"] == "unsafe_integer"
