#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Build a reviewer-friendly governance benchmark package.

The package is explicitly scoped to REMORA as a governance overlay.
It should never be interpreted as a claim that REMORA replaces agents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
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

# Dependency lockfiles hashed into the manifest so a reviewer can pin the exact
# environment the pack was built against.
LOCKFILES = ["requirements-lock.txt", "frontend/package-lock.json"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, timeout=15
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def build_package(
    *,
    repo_root: Path,
    out_dir: Path,
    zip_path: Path,
    include_zip: bool = True,
) -> dict:
    # Clean the output directory first so stale files from a previous build can
    # never be carried into the ZIP (P0-1). rglob-guarded rmtree keeps this safe
    # if out_dir is misconfigured to something outside artifacts/.
    if out_dir.exists():
        assert out_dir.resolve() != repo_root.resolve(), "refusing to wipe repo root"
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    missing: list[str] = []
    file_sha256: dict[str, str] = {}

    for rel in PACKAGE_FILES:
        src = repo_root / rel
        dst = out_dir / rel
        if not src.exists():
            missing.append(rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        # Verify the copy is byte-identical to the canonical source.
        src_hash = _sha256(src)
        assert _sha256(dst) == src_hash, f"copy mismatch for {rel}"
        copied.append(rel)
        file_sha256[rel] = src_hash

    lockfile_sha256 = {
        rel: _sha256(repo_root / rel)
        for rel in LOCKFILES
        if (repo_root / rel).exists()
    }

    commit_sha = _git(repo_root, "rev-parse", "HEAD")
    # "clean" means the SOURCE tree is clean; the pack output itself is always
    # rewritten by this build, so exclude it from the check.
    status = _git(repo_root, "status", "--porcelain")
    if status is None:
        source_clean: bool | None = None
    else:
        dirty = [ln for ln in status.splitlines()
                 if "governance-benchmark-pack" not in ln]
        source_clean = len(dirty) == 0
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "REMORA governance overlay benchmark package",
        "scope_note": "This package evaluates governance performance and safety controls, not agent replacement capability.",
        "commit_sha": commit_sha,
        "worktree_clean": source_clean,
        "lockfile_sha256": lockfile_sha256,
        "copied_files": copied,
        "file_sha256": file_sha256,
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
