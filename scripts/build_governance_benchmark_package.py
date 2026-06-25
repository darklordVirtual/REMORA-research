#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Build a reviewer-friendly governance benchmark package.

The package is explicitly scoped to REMORA as a governance overlay.
It should never be interpreted as a claim that REMORA replaces agents.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "artifacts" / "governance-benchmark-pack"
DEFAULT_ZIP = ROOT / "artifacts" / "governance-benchmark-pack.zip"

PACKAGE_FILES = [
    "artifacts/benchmark_summary.json",
    "artifacts/benchmark_stats.json",
    "artifacts/benchmark_stats_n500.json",
    "artifacts/toolcall_benchmark_v2.json",
    "artifacts/rag_adversarial_test.json",
    "docs/results_snapshot.md",
    "docs/claim_register.md",
    "NEGATIVE_RESULTS.md",
    "README.md",
]


def build_package(
    *,
    repo_root: Path,
    out_dir: Path,
    zip_path: Path,
    include_zip: bool = True,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    missing: list[str] = []

    for rel in PACKAGE_FILES:
        src = repo_root / rel
        dst = out_dir / rel
        if not src.exists():
            missing.append(rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "REMORA governance overlay benchmark package",
        "scope_note": "This package evaluates governance performance and safety controls, not agent replacement capability.",
        "copied_files": copied,
        "missing_files": missing,
        "file_count": len(copied),
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if include_zip:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in out_dir.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, arcname=file_path.relative_to(out_dir))

    return {
        "out_dir": str(out_dir),
        "zip_path": str(zip_path) if include_zip else "",
        "copied_files": len(copied),
        "missing_files": len(missing),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build REMORA governance benchmark package")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()

    result = build_package(
        repo_root=ROOT,
        out_dir=args.out_dir,
        zip_path=args.zip,
        include_zip=not args.no_zip,
    )
    print(json.dumps({"status": "ok", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
