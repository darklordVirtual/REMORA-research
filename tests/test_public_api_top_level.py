# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The top-level `remora` surface is snapshot-gated, like `remora.sdk`.

`remora.sdk`'s 36 symbols were gated against a committed snapshot and
re-checked against the installed wheel in CI. `remora.__all__`'s 90 were
guarded by exactly one negative assertion about six unrelated names — and
the top-level surface is the one the README teaches. Anything else could be
removed or renamed silently.

Regenerate deliberately with `python scripts/export_public_api.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "artifacts" / "sdk" / "public_api_top_level_v1.json"
)


def test_snapshot_exists() -> None:
    assert SNAPSHOT.is_file(), (
        "top-level API snapshot missing; run scripts/export_public_api.py"
    )


def test_public_surface_matches_snapshot_exactly() -> None:
    import remora

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert snapshot["module"] == "remora"
    declared = set(snapshot["symbols"])
    actual = set(remora.__all__)
    removed = declared - actual
    added = actual - declared
    assert not removed, (
        f"public symbols removed without a snapshot update: {sorted(removed)}"
    )
    assert not added, (
        f"public symbols added without a snapshot update: {sorted(added)}"
    )


def test_every_snapshot_symbol_actually_resolves() -> None:
    """A name in __all__ that cannot be imported is worse than a missing one."""
    import remora

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    unresolved = [s for s in snapshot["symbols"] if not hasattr(remora, s)]
    assert unresolved == [], unresolved
