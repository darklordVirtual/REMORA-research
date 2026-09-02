# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Emit the release manifest a downstream product repository pins.

The product repository (``assured-agent-execution``) must never install
REMORA from ``master`` or copy its internal modules. It consumes a
*versioned, hash-identified* artifact set instead, and this script is what
produces the identity half of that contract:

    remora_assurance-<version>-py3-none-any.whl   the SDK + control plane
    schemas/openapi.json                the REST contract
    artifacts/sdk/public_api_v1.json    the public SDK surface

The manifest records a SHA-256 for each, plus the exact commit and whether
the worktree was clean when it was built. A dirty worktree is recorded as
``worktree_clean: false`` rather than refused here — the *promotion* gate
is where that becomes disqualifying (see
``scripts/check_claim_provenance.py``); a build manifest that quietly
omitted it would hide the fact instead of surfacing it.

Usage::

    python scripts/build_release_manifest.py --wheel dist/remora_assurance-*.whl

Stdlib only, so it runs in a clean release environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path: Path) -> str:
    """LF-normalized for text, raw for binary.

    Text artifacts are normalized so a checkout on Windows and one on
    Linux produce the same digest; the wheel is binary and must not be
    touched.
    """
    data = path.read_bytes()
    if path.suffix in {".json", ".yaml", ".yml", ".md", ".txt"}:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build_manifest(wheel: Path, *, generated_at: str | None = None) -> dict:
    if not wheel.is_file():
        raise SystemExit(f"wheel not found: {wheel}")

    openapi = ROOT / "schemas" / "openapi.json"
    sdk_surface = ROOT / "artifacts" / "sdk" / "public_api_v1.json"
    lifecycle = ROOT / "schemas" / "execution_lifecycle_v1.yaml"
    tool_spec = ROOT / "schemas" / "tool_spec_v1.yaml"
    postcondition = ROOT / "schemas" / "postcondition_contract_v1.yaml"
    for required in (openapi, sdk_surface, lifecycle, tool_spec,
                     postcondition):
        if not required.is_file():
            raise SystemExit(f"required artifact missing: {required}")

    surface = json.loads(sdk_surface.read_text(encoding="utf-8"))
    version = wheel.name.split("-")[1]

    return {
        "manifest_version": 1,
        "remora_core_version": version,
        "git_commit": _git("rev-parse", "HEAD"),
        "worktree_clean": _git("status", "--porcelain") == "",
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "artifacts": {
            "wheel": {
                "filename": wheel.name,
                "sha256": sha256_file(wheel),
                "size_bytes": wheel.stat().st_size,
            },
            "openapi": {
                "filename": "openapi.json",
                "sha256": sha256_file(openapi),
            },
            "sdk_public_api": {
                "filename": "public_api_v1.json",
                "sha256": sha256_file(sdk_surface),
                "symbol_count": len(surface.get("symbols", [])),
            },
            "execution_lifecycle_schema": {
                "filename": "execution_lifecycle_v1.yaml",
                "sha256": sha256_file(lifecycle),
            },
            # The two frozen contracts a consumer verifies against. Without
            # them in the manifest, a product could pin the wheel and still
            # disagree with REMORA about what a ToolSpec is or what an
            # effect status means — which is precisely the drift the pin
            # exists to prevent.
            "tool_spec_schema": {
                "filename": "tool_spec_v1.yaml",
                "sha256": sha256_file(tool_spec),
            },
            "postcondition_contract_schema": {
                "filename": "postcondition_contract_v1.yaml",
                "sha256": sha256_file(postcondition),
            },
        },
        "sdk": {
            "module": surface.get("module", "remora.sdk"),
            "symbols": surface.get("symbols", []),
            "extras_required": ["sdk"],
        },
        # Stated, not implied: what a consumer may rely on and what it may
        # not. The product repository's compatibility test asserts the
        # first; the second is why it must not import anything else.
        "consumer_contract": {
            "stable_namespace": "remora.sdk",
            "internal_namespaces": [
                "remora.policy", "remora.enforcement", "remora.governance",
                "servers",
            ],
            "backward_compatibility": (
                "pre-1.0: breaking changes allowed in minor versions, always "
                "CHANGELOG-recorded; the public surface is snapshot-gated"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, help="path to the built wheel")
    parser.add_argument("--out", default="-", help="output path, or - for stdout")
    args = parser.parse_args()

    manifest = build_manifest(Path(args.wheel))
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        sys.stdout.write(rendered)
    else:
        Path(args.out).write_text(rendered, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    if not manifest["worktree_clean"]:
        print(
            "WARNING: built from a DIRTY worktree — recorded in the manifest; "
            "a promoted release must be built from a clean checkout",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
