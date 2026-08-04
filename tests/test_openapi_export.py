# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OpenAPI contract is a committed, drift-gated artifact.

A contract that only exists at runtime cannot be reviewed, diffed, or used to
generate clients reproducibly. schemas/openapi.json is the canonical export;
scripts/export_openapi.py --check fails when the live app and the committed
document diverge, and CI runs the check so contract drift is a red build,
not a surprise for a client generator.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "scripts" / "export_openapi.py"
ARTIFACT = ROOT / "schemas" / "openapi.json"


def test_committed_contract_matches_the_live_app() -> None:
    result = subprocess.run(
        [sys.executable, str(EXPORT), "--check"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"OpenAPI drift:\n{result.stdout}\n{result.stderr}\n"
        "Regenerate with: python scripts/export_openapi.py"
    )


def test_committed_contract_carries_the_typed_execution_models() -> None:
    doc = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    schemas = doc["components"]["schemas"]
    for model in ("ExecutionAssessResponse", "ExecutionExecuteResponse",
                  "ErrorDetail", "ToolCallRequest"):
        assert model in schemas, f"{model} missing from committed contract"
    assert doc["info"]["title"] == "REMORA API"
