# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Frozen cross-language canonical-JSON golden vectors (Phase 6).

The envelope hash contract depends on Python and the TypeScript worker
producing byte-identical canonical JSON. These vectors freeze the agreement
domain and — just as importantly — pin the four KNOWN divergences
(integral-valued floats, negative zero, 1e20 positional notation, integers
beyond 2^53) so neither language can drift silently and no new payload shape
can wander into the divergent zone unnoticed. Changing an expected string is
a hash-contract change and requires an explicit migration.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_VECTORS = json.loads(
    (_REPO_ROOT / "tests" / "golden" / "canonical_json_vectors_v1.json").read_text(
        encoding="utf-8"
    )
)
_WORKER_DIR = _REPO_ROOT / "workers" / "agent-control"


def _python_canonical(data: object) -> str:
    # The exact form remora.governance.tenant_chain hashes.
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def test_python_matches_every_agreed_vector() -> None:
    for case in _VECTORS["agreed"]:
        assert _python_canonical(case["value"]) == case["canonical"], case


def test_python_divergent_column_is_pinned() -> None:
    for case in _VECTORS["known_divergent"]:
        value = json.loads(case["value_json"])
        assert _python_canonical(value) == case["python"], case["reason"]


def test_divergent_cases_documented_with_reasons() -> None:
    for case in _VECTORS["known_divergent"]:
        assert case["python"] != case["typescript"], (
            "a 'known_divergent' case now agrees — move it to 'agreed' via an "
            "explicit vector-file update"
        )
        assert case.get("reason")


def test_typescript_matches_agreed_and_pinned_divergent(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not (_WORKER_DIR / "node_modules" / "esbuild").exists():
        pytest.skip("esbuild not installed in workers/agent-control")

    bundle = tmp_path / "envelope.mjs"
    subprocess.run(
        [
            "npx", "esbuild", str(_WORKER_DIR / "src" / "envelope.ts"),
            "--bundle", "--format=esm", "--platform=node",
            f"--outfile={bundle}",
        ],
        cwd=_WORKER_DIR, check=True, capture_output=True, shell=os.name == "nt",
    )
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        f"import {{ canonicalJson }} from {json.dumps(bundle.as_uri())};\n"
        f"const vectors = {json.dumps(_VECTORS)};\n"
        "const out = {agreed: vectors.agreed.map(c => canonicalJson(c.value)),\n"
        "  divergent: vectors.known_divergent.map(c => canonicalJson(JSON.parse(c.value_json)))};\n"
        "console.log(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(driver)], cwd=_WORKER_DIR, check=True,
        capture_output=True, text=True,
    )
    out = json.loads(result.stdout.strip().splitlines()[-1])

    for case, got in zip(_VECTORS["agreed"], out["agreed"]):
        assert got == case["canonical"], case
    for case, got in zip(_VECTORS["known_divergent"], out["divergent"]):
        assert got == case["typescript"], case["reason"]
