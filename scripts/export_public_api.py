#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regenerate the committed public-API snapshots.

Two surfaces are gated:

``remora.sdk``
    The narrow, versioned integration namespace third parties are told to
    import (``artifacts/sdk/public_api_v1.json``).
``remora``
    The top-level convenience surface the README actually teaches
    (``artifacts/sdk/public_api_top_level_v1.json``). It was ungated until
    2026-08-20 — 90 names guarded by one negative assertion — which meant the
    surface being advertised was the one nothing protected.

Changing either snapshot is a deliberate, reviewed act. Run this script, read
the diff, and say in the commit message why a symbol appeared or vanished.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

TOP_LEVEL = REPO_ROOT / "artifacts" / "sdk" / "public_api_top_level_v1.json"


def main() -> int:
    import remora

    snapshot = json.loads(TOP_LEVEL.read_text(encoding="utf-8"))
    snapshot["symbols"] = sorted(remora.__all__)
    TOP_LEVEL.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {TOP_LEVEL.relative_to(REPO_ROOT)} "
          f"({len(snapshot['symbols'])} symbols)")
    print("For remora.sdk, run scripts/export_sdk_public_api.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
