# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-13 slice 1: the public SDK surface is snapshot-gated.

``artifacts/sdk/public_api_v1.json`` is the committed record of what
``remora.sdk`` exports. Removing or renaming a symbol without updating
the snapshot (a reviewed, deliberate act) fails CI — a third party's
import can never silently disappear. Regenerate with
``python scripts/export_sdk_public_api.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[1] / "artifacts" / "sdk" / "public_api_v1.json"


def test_snapshot_exists() -> None:
    assert SNAPSHOT.is_file(), (
        "public API snapshot missing; run scripts/export_sdk_public_api.py"
    )


def test_public_surface_matches_snapshot_exactly() -> None:
    import remora.sdk as sdk

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert snapshot["module"] == "remora.sdk"
    declared = set(snapshot["symbols"])
    actual = set(sdk.__all__)
    removed = declared - actual
    added = actual - declared
    assert not removed, f"public symbols removed without snapshot update: {sorted(removed)}"
    assert not added, f"public symbols added without snapshot update: {sorted(added)}"


def test_every_declared_symbol_is_importable() -> None:
    import remora.sdk as sdk

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for name in snapshot["symbols"]:
        assert hasattr(sdk, name), f"declared public symbol not exported: {name}"


def test_all_is_sorted_and_unique() -> None:
    import remora.sdk as sdk

    assert list(sdk.__all__) == sorted(set(sdk.__all__))
