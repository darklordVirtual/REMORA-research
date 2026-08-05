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
        # get_closest_marker, NOT `in item.keywords`: keywords also contain
        # parametrization ids, so a test parametrized over the string "live"
        # (e.g. the production-environment aliases prod/production/live) was
        # silently skipped as a network test. A gate that skips itself when an
        # unrelated parameter happens to share its name is worse than no gate —
        # it reports green for a case that never ran.
        if (item.get_closest_marker("live") is not None
                or item.get_closest_marker("live_replay_heavy") is not None):
            item.add_marker(skip_live)
