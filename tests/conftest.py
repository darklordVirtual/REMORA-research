# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pytest collection guards for network-dependent tests.

Live tests (``@pytest.mark.live`` / ``@pytest.mark.live_replay_heavy``) reach a
deployed Cloudflare Worker over the network. ``addopts`` in ``pyproject.toml``
deselects them by default with ``-m 'not live and not live_replay_heavy'`` — but
a reviewer who passes their own marker expression (for example
``pytest -m "not slow"``) *overrides* that default ``-m``, re-collecting and then
running the live tests, which produces a spurious network failure on a clean
checkout.

This hook skips live tests at collection time unless ``REMORA_LIVE`` is set in
the environment, so the guard survives any ``-m`` override instead of relying on
marker selection. Default runs are unaffected: ``addopts`` still deselects the
live tests before this hook sees them, so nothing new is skipped there.
"""
import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip live/network tests unless REMORA_LIVE is explicitly set."""
    if os.environ.get("REMORA_LIVE"):
        return
    skip_live = pytest.mark.skip(
        reason="live test: set REMORA_LIVE=1 to run against the deployed Worker",
    )
    for item in items:
        if "live" in item.keywords or "live_replay_heavy" in item.keywords:
            item.add_marker(skip_live)
