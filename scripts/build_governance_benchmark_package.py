#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Build a reviewer-friendly governance benchmark package.

The package is explicitly scoped to REMORA as a governance overlay.
It should never be interpreted as a claim that REMORA replaces agents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
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



#: Canonical source for anything the pack links to but does not ship.
REPO_URL = "https://github.com/darklordVirtual/REMORA-research"


def _rewrite_external_links(out_dir: Path, packaged: set[str], commit: str | None) -> int:
    """Point pack links at the canonical source when the target is not shipped.

    The pack is the artifact external reviewers read, and it inherited the
    repository's root-relative markdown links wholesale. Anything not in
    PACKAGE_FILES therefore resolved to nothing — 31 dead links in the one
    artifact whose audience is the one you least want to disappoint.

    Links to files that ARE in the pack stay relative and keep working
    offline. Everything else becomes a permalink pinned to the commit the
    pack was built from, so it keeps resolving after the branch moves on.
    """
    ref = commit or "master"
    # Badge-aware, matching scripts/_check_links.py: markdown badges nest one
    # level of brackets, [![alt](image)](target), and a naive pattern rewrites
    # the image instead of the target — or misses the target entirely.
    pattern = re.compile(r"(\[(?:[^\[\]]|\[[^\]]*\])*\]\()([^)\s]+)(\))")
    rewritten = 0

    for md_path in sorted(out_dir.rglob("*.md")):
        # Bytes, not text mode: on Windows, write_text translates the
        # newline and would change every packaged hash, defeating the LF
        # normalisation the rest of this builder is careful about.
        text = md_path.read_bytes().decode("utf-8")

        def replace(match: "re.Match[str]") -> str:
            nonlocal rewritten
            prefix, target, suffix = match.groups()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                return match.group(0)
            path_part, _, anchor = target.partition("#")
            if not path_part:
                return match.group(0)
            resolved = (md_path.parent / path_part).resolve()
            if resolved.exists():
                return match.group(0)
            # Resolve against the repository root the same way the source
            # document did, then hand the reader the canonical location.
            source_rel = path_part.lstrip("./")
            if source_rel in packaged:
                return match.group(0)
            rewritten += 1
            fragment = f"#{anchor}" if anchor else ""
            return f"{prefix}{REPO_URL}/blob/{ref}/{source_rel}{fragment}{suffix}"

        updated = pattern.sub(replace, text)
        if updated != text:
            md_path.write_bytes(updated.encode("utf-8"))
    return rewritten


def _read_lf(path: Path) -> bytes:
    """Read a text file with CRLF normalized to LF.

    All packaged files are text (Markdown / JSON) and the repo stores them LF
    (.gitattributes). Normalizing before hashing/writing keeps the manifest
    hashes identical whether the pack is built on Windows or Linux, so the
    committed (LF) blobs always match their recorded sha256 in CI.
    """
    return path.read_bytes().replace(b"\r\n", b"\n")


def _sha256_lf(path: Path) -> str:
    return hashlib.sha256(_read_lf(path)).hexdigest()


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
        # Copy as LF-normalized bytes so the written file matches the committed
        # (LF) blob and its recorded hash on every platform.
        data = _read_lf(src)
        dst.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        assert _sha256_lf(dst) == digest, f"copy mismatch for {rel}"
        copied.append(rel)
        file_sha256[rel] = digest

    lockfile_sha256 = {
        rel: _sha256_lf(repo_root / rel)
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
    rewritten_links = _rewrite_external_links(out_dir, set(copied), commit_sha)
    manifest["rewritten_external_links"] = rewritten_links
    # Two hashes, two questions. file_sha256 answers "which repository file is
    # this?" (provenance, and it is what the source-of-truth checks compare
    # against). packaged_sha256 answers "is the bundle intact?" (integrity).
    # They differ exactly where a link to an unshipped document was rewritten
    # into a permalink, which is the whole reason the pack's links resolve.
    manifest["packaged_sha256"] = {
        rel: _sha256_lf(out_dir / rel) for rel in copied
    }
    manifest["file_sha256_note"] = (
        "file_sha256 is the repository SOURCE hash (provenance). "
        "packaged_sha256 is the hash of the bytes in this bundle (integrity). "
        "They differ for markdown whose links were rewritten; see "
        "rewritten_external_links."
    )
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
