# SPDX-License-Identifier: BUSL-1.1
"""Structural single-execution-path guards for the agent-control Worker.

Pins the ADR-single-authoritative-execution-path floor by executing the REAL
worker module (esbuild bundle, node): every write-effect tool is
unconditionally approval-gated in code, and deployment configuration can only
ADD gated tools — never remove one. A new catalog tool declared high-risk but
missing from WRITE_IMPACT_TOOLS fails here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKER_DIR = _REPO_ROOT / "workers" / "agent-control"
_INDEX_TS = _WORKER_DIR / "src" / "index.ts"

_DRIVER = """
import {
  TOOL_CATALOG, TOOL_RISK_TIER, WRITE_IMPACT_TOOLS, requiresApproval,
} from BUNDLE;

console.log(JSON.stringify({
  catalog_tools: TOOL_CATALOG.map((t) => t.name),
  risk_tiers: TOOL_RISK_TIER,
  write_impact_tools: [...WRITE_IMPACT_TOOLS],
  write_gated_with_empty_config: requiresApproval("store_artifact", ""),
  write_gated_with_other_config: requiresApproval("store_artifact", "some_other_tool"),
  config_can_add: requiresApproval("dce_search_law", "dce_search_law"),
  read_not_gated_by_default: requiresApproval("dce_search_law", ""),
}));
"""


@pytest.fixture(scope="module")
def worker_facts(tmp_path_factory: pytest.TempPathFactory) -> dict:
    if not _INDEX_TS.exists():
        pytest.skip("worker module not present")
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not (_WORKER_DIR / "node_modules" / "esbuild").exists():
        pytest.skip("esbuild not installed in workers/agent-control")

    tmp_path = tmp_path_factory.mktemp("agent_control_single_path")
    bundle = tmp_path / "index.mjs"
    subprocess.run(
        [
            "npx", "esbuild", str(_INDEX_TS),
            "--bundle", "--format=esm", "--platform=node",
            f"--outfile={bundle}",
        ],
        cwd=_WORKER_DIR,
        check=True,
        capture_output=True,
        shell=os.name == "nt",
    )
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        _DRIVER.replace("BUNDLE", json.dumps(bundle.as_uri())), encoding="utf-8"
    )
    result = subprocess.run(
        ["node", str(driver)], cwd=_WORKER_DIR, check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_write_tool_gated_regardless_of_config(worker_facts: dict) -> None:
    assert worker_facts["write_gated_with_empty_config"] is True
    assert worker_facts["write_gated_with_other_config"] is True


def test_config_can_only_add_never_remove(worker_facts: dict) -> None:
    assert worker_facts["config_can_add"] is True
    assert worker_facts["read_not_gated_by_default"] is False


def test_every_high_risk_catalog_tool_is_write_gated(worker_facts: dict) -> None:
    high_risk = {t for t, tier in worker_facts["risk_tiers"].items() if tier == "high"}
    assert high_risk <= set(worker_facts["write_impact_tools"]), (
        "high-risk tool missing from WRITE_IMPACT_TOOLS — the structural floor "
        "does not cover it"
    )


def test_write_impact_tools_exist_in_catalog(worker_facts: dict) -> None:
    assert set(worker_facts["write_impact_tools"]) <= set(worker_facts["catalog_tools"])


def test_retired_approval_tool_not_in_catalog(worker_facts: dict) -> None:
    assert "audit_decision" not in worker_facts["catalog_tools"]
