# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Export (or check) the public API snapshot of ``remora.sdk``.

The snapshot at ``artifacts/sdk/public_api_v1.json`` is the committed
record of the SDK surface; ``tests/test_sdk_public_api.py`` fails when
``remora.sdk.__all__`` and the snapshot diverge, so removing or adding a
public symbol is always a deliberate, reviewed change.

Usage:
    python scripts/export_sdk_public_api.py          # rewrite snapshot
    python scripts/export_sdk_public_api.py --check  # exit 1 on drift
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO_ROOT / "artifacts" / "sdk" / "public_api_v1.json"


def build_snapshot() -> dict:
    sys.path.insert(0, str(REPO_ROOT))
    import remora.sdk as sdk

    symbols: dict[str, str] = {}
    for name in sorted(sdk.__all__):
        obj = getattr(sdk, name)
        if inspect.isclass(obj) and issubclass(obj, Exception):
            kind = "exception"
        elif inspect.isclass(obj):
            kind = "class"
        elif inspect.isfunction(obj):
            kind = "function"
        else:
            kind = "object"
        symbols[name] = kind
    return {"version": 1, "module": "remora.sdk", "symbols": symbols}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail (exit 1) if the snapshot is stale")
    args = parser.parse_args()

    snapshot = build_snapshot()
    rendered = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"

    if args.check:
        if not SNAPSHOT.is_file() or SNAPSHOT.read_text(encoding="utf-8") != rendered:
            print("public API snapshot is stale; run "
                  "python scripts/export_sdk_public_api.py", file=sys.stderr)
            return 1
        print("public API snapshot is current")
        return 0

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {SNAPSHOT.relative_to(REPO_ROOT)} "
          f"({len(snapshot['symbols'])} public symbols)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
