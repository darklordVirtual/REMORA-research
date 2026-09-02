# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The committed what-if analysis of the ``try`` presets must match a fresh
run: a policy change that moves the deployment-fact boundary has to show up
as a diff in ``artifacts/demo/whatif_presets_v1.json``, not go unnoticed."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

pytestmark = pytest.mark.docgate


def test_whatif_presets_artifact_is_current(repo_root):
    r = subprocess.run(
        [sys.executable, "scripts/generate_whatif_presets.py", "--check"],
        capture_output=True, text=True, cwd=repo_root,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_whatif_presets_artifact_states_the_boundary(repo_root):
    """The front page says a critical production write cannot be lifted by a
    model; the committed artifact must carry that statement for the preset."""
    data = json.loads((repo_root / "artifacts/demo/whatif_presets_v1.json").read_text())
    assert data["regenerate"] == "python scripts/generate_whatif_presets.py"
    by_name = {p["call"]["name"]: p for p in data["presets"]}
    drop = by_name["drop_database"]["what_if"]
    for profile in ("default", "execution_profile"):
        assert drop[profile]["confidence_can_lift"] is False
        assert drop[profile]["model_signals_alone"] is None
    assert drop["default"]["deployment_facts_required"] is True
    assert drop["execution_profile"]["reachable"] is False
    injection = by_name["run_command"]["what_if"]["default"]
    assert injection["hard_guard"] == "admission_firewall_blocked"
