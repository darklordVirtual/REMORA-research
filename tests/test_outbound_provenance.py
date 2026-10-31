# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Outbound contribution metadata must stay structurally honest."""
from __future__ import annotations

import copy
import importlib.util
import json

import pytest
import yaml


@pytest.mark.docgate
def test_outbound_contribution_ledger(repo_root):
    path = repo_root / "scripts/check_outbound_provenance.py"
    spec = importlib.util.spec_from_file_location("outbound_provenance", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    schema = json.loads((repo_root / module.SCHEMA).read_text(encoding="utf-8"))
    data = yaml.safe_load((repo_root / module.REGISTER).read_text(encoding="utf-8"))
    assert module.validate(data, schema, repo_root) == []

    duplicate = copy.deepcopy(data)
    duplicate["records"].append(copy.deepcopy(duplicate["records"][0]))
    assert any("duplicate" in e for e in module.validate(duplicate, schema, repo_root))

    unpinned = copy.deepcopy(data)
    unpinned["records"][0].pop("merge_commit")
    assert any("merge_commit" in e for e in module.validate(unpinned, schema, repo_root))

    false_merge = copy.deepcopy(data)
    false_merge["records"][-1]["merge_commit"] = "0" * 40
    assert any("merge_commit" in e for e in module.validate(false_merge, schema, repo_root))

    bad_path = copy.deepcopy(data)
    bad_path["records"][0]["target_paths"].append("../remora/private.py")
    assert any("unsafe target path" in e for e in module.validate(bad_path, schema, repo_root))
