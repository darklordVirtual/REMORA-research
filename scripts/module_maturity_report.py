#!/usr/bin/env python3
"""Generate a module maturity report for REMORA.

Usage:
    python scripts/module_maturity_report.py
    python scripts/module_maturity_report.py --json
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

REMORA_ROOT = Path(__file__).resolve().parents[1]
REMORA_PKG = REMORA_ROOT / "remora"

STABILITY_LABELS = {
    "core": "CORE         ✓",
    "experimental": "EXPERIMENTAL ⚠",
    "research_only": "RESEARCH     🔬",
    None: "UNMARKED     ?",
}


def scan() -> list[dict]:
    results = []
    for py_file in sorted(REMORA_PKG.rglob("*.py")):
        if py_file.name.startswith("_") and py_file.name != "__init__.py":
            continue
        rel = py_file.relative_to(REMORA_ROOT)
        module_name = str(rel).replace("/", ".").removesuffix(".py")
        try:
            mod = importlib.import_module(module_name)
            stability = getattr(mod, "__stability__", None)
        except Exception as exc:
            stability = f"ERROR: {exc}"
        results.append({"module": module_name, "stability": stability, "path": str(rel)})
    return results


def main() -> None:
    results = scan()
    if "--json" in sys.argv:
        print(json.dumps(results, indent=2))
        return

    print(f"\n{'Module':<58} {'Stability'}")
    print("-" * 80)
    unmarked = []
    for r in results:
        label = STABILITY_LABELS.get(r["stability"], f"UNKNOWN ({r['stability']})")
        print(f"{r['module']:<58} {label}")
        if r["stability"] is None:
            unmarked.append(r["module"])

    print(f"\n{len(results)} modules scanned.")
    if unmarked:
        print(f"\n⚠  {len(unmarked)} modules lack __stability__ marker:")
        for m in unmarked[:10]:
            print(f"   - {m}")
        if len(unmarked) > 10:
            print(f"   ... and {len(unmarked) - 10} more")
    else:
        print("\n✓ All modules have stability markers.")


if __name__ == "__main__":
    main()
