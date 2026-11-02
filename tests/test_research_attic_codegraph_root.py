# SPDX-License-Identifier: BUSL-1.1
"""W-08 / F-10: the attic CodeGraph module resolves paths from the repository root.

It moved from remora/ into remora/research_attic/ (#289) without updating
``parents[1]``, so its catalog path pointed at remora/workers/... and the
local index read nothing.
"""
from __future__ import annotations

from pathlib import Path

from remora.research_attic import codegraph

_ROOT = Path(__file__).resolve().parents[1]


def test_repo_root_is_the_repository_root() -> None:
    assert codegraph._REPO_ROOT == _ROOT


def test_catalog_source_resolves_to_the_worker_file() -> None:
    assert codegraph._PATHS_TS == _ROOT / "workers" / "agent-control" / "src" / "codegraph.paths.ts"
    assert codegraph._PATHS_TS.is_file()
