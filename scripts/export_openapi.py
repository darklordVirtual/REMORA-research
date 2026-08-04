#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Export the canonical OpenAPI document to schemas/openapi.json.

The committed document is the reviewable, diffable contract a client
generator consumes. ``--check`` exits non-zero when the live app no longer
matches the committed copy — run in CI so contract drift is a red build.

The export is deterministic for a fixed dependency set (sorted keys, stable
route order); fastapi/pydantic are pinned by requirements-lock.txt, so the
CI check and a locked local environment produce byte-identical output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify the committed document instead of writing")
    parser.add_argument("--out", default=str(ROOT / "schemas" / "openapi.json"))
    args = parser.parse_args()

    from servers.api import app

    text = json.dumps(app.openapi(), indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"
    out = Path(args.out)

    if args.check:
        committed = out.read_text(encoding="utf-8") if out.exists() else ""
        if committed != text:
            print(f"OpenAPI drift: {out} does not match the live contract.\n"
                  "Regenerate with: python scripts/export_openapi.py",
                  file=sys.stderr)
            return 1
        print(f"OpenAPI contract matches {out}")
        return 0

    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
