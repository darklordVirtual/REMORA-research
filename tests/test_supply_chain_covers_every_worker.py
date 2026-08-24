# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every shipped npm package is audited (RMR-007).

The npm dependency audit ran over a hand-maintained list of directories, and
``workers/mcp-gateway`` was not on it. Of everything in the repository the
gateway is the component that holds execution authority and the downstream
credentials, so it was the one package whose dependencies went unaudited --
the inverse of the order anyone would choose deliberately.

Nothing had gone wrong: the audit is clean. The finding is that no gate would
have told us either way, and that a list maintained by hand drifts silently
every time a directory is added.

This test is the gate. It compares the workflow's matrix against what is
actually on disk, so a new worker cannot ship without an audit leg -- the
failure mode is a red test at the moment the package appears, rather than a
gap nobody notices until a reader goes looking.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "supply-chain.yml"


def _audit_dirs() -> set[str]:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in doc["jobs"].values():
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        if "dir" in matrix:
            return set(matrix["dir"])
    raise AssertionError("no job in supply-chain.yml carries a `dir` matrix")


def _shipped_packages() -> set[str]:
    """Directories with a package.json AND a lockfile, excluding node_modules.

    A lockfile is the thing an audit reads, so a package without one is not
    something this gate can require coverage of.
    """
    found = set()
    for manifest in ROOT.glob("*/package.json"):
        if (manifest.parent / "package-lock.json").exists():
            found.add(manifest.parent.name)
    for manifest in ROOT.glob("workers/*/package.json"):
        if (manifest.parent / "package-lock.json").exists():
            found.add("workers/" + manifest.parent.name)
    return found


def test_every_shipped_package_is_audited():
    missing = _shipped_packages() - _audit_dirs()
    assert not missing, (
        f"these packages ship and are not audited: {sorted(missing)}. Add "
        "them to the `dir` matrix in supply-chain.yml, or this repository is "
        "claiming a dependency audit it does not perform")


def test_the_gateway_specifically_is_covered():
    """Named, because it is the one that was missing and the one that matters.

    A generic set-difference test would keep passing if someone removed the
    gateway from the matrix and its lockfile in the same change.
    """
    assert "workers/mcp-gateway" in _audit_dirs()


def test_the_matrix_names_nothing_that_does_not_exist():
    """A stale entry is a green leg that audits nothing.

    Harmless in effect and misleading in the summary, which is the same shape
    as every other finding in this pass.
    """
    stale = {d for d in _audit_dirs() if not (ROOT / d / "package.json").exists()}
    assert not stale, f"audited directories that do not exist: {sorted(stale)}"


def test_the_gateway_sbom_is_generated():
    """The SBOM covered the Python package and the frontend, and no worker.

    Only the gateway is added here. The other four workers remain uncovered
    and this test deliberately does not assert otherwise -- claiming complete
    worker coverage while generating one of five is the kind of prose this
    repository keeps having to retract.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "sbom-mcp-gateway.cdx.json" in text
    # Generated AND uploaded. Generating it and dropping it on the floor would
    # pass a substring check on the filename alone.
    upload = text.split("Upload SBOM artifacts", 1)
    assert len(upload) == 2, "the upload step was renamed or removed"
    assert "sbom-mcp-gateway.cdx.json" in upload[1]
