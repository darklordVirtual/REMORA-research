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


# ---------------------------------------------------------------------------
# Shared fixtures (self-review 2026-08-20)
# ---------------------------------------------------------------------------
#
# This file held one hook and zero fixtures, and the cost was measurable:
# RemoraDecisionEngine() was constructed 141 times across 41 files,
# PolicyObservation 274 times across 43, and 83 files each recomputed the repo
# root with their own parents[N] expression. These are the pieces that every
# test needs and none of them should be re-deriving.
#
# They are deliberately few. A fixture that hides which observation a test
# actually ran against would make the suite less readable, not more, so
# `observation` is a FACTORY: the test still states the fields it cares about,
# and only the boilerplate disappears.

from pathlib import Path  # noqa: E402
from typing import Any, Callable  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root.

    83 test files computed this independently with `parents[1]` or
    `parents[2]`, which silently breaks the moment a test moves into a
    subdirectory.
    """
    return _ROOT


@pytest.fixture
def engine():
    """A default RemoraDecisionEngine: every opt-in ACCEPT path off."""
    from remora.policy.decision_engine import RemoraDecisionEngine

    return RemoraDecisionEngine()


@pytest.fixture
def observation() -> "Callable[..., Any]":
    """Factory for a PolicyObservation with a question already supplied.

    A factory rather than a ready-made object on purpose: which fields a test
    sets IS the test, so it must stay visible at the call site.

        def test_x(engine, observation):
            report = engine.decide(observation(risk_tier="critical"))
    """
    from remora.policy.observation import PolicyObservation

    def _make(question: str = "probe question", **fields: Any) -> PolicyObservation:
        return PolicyObservation(question=question, **fields)

    return _make


@pytest.fixture
def signing_key() -> bytes:
    """A deterministic HMAC key for signing tests. Never a real key."""
    return b"test-signing-key-do-not-use-in-production"
