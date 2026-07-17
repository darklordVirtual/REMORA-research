# Author: Stian Skogbrott
# License: Apache-2.0
"""The documentation index must be complete and coherent — enforced, not hoped.

Two invariants:

1. **Coverage** — every file under docs/ (recursively, except figure assets
   and the index itself) is individually referenced in docs/README.md.
   Adding a document without indexing it fails this test.
2. **No dead entries** — every relative link in docs/README.md resolves to an
   existing file, so the index cannot reference deleted documents.
"""
from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
INDEX = DOCS / "README.md"

# Folder-level entries are allowed only for pure asset directories.
ASSET_DIRS = ("figures",)

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(#[^)]*)?\)")


def _index_text() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_every_docs_file_is_indexed() -> None:
    index = _index_text()
    missing: list[str] = []
    for path in sorted(DOCS.rglob("*")):
        if not path.is_file() or path == INDEX:
            continue
        rel = path.relative_to(DOCS).as_posix()
        if rel.split("/")[0] in ASSET_DIRS:
            continue
        if rel not in index:
            missing.append(rel)
    assert not missing, (
        "docs/README.md does not index these files (add a row with a one-line "
        f"purpose, or archive them): {missing}"
    )


def test_index_has_no_dead_links() -> None:
    dead: list[str] = []
    for match in LINK_RE.finditer(_index_text()):
        target = match.group(1)
        if target.startswith(("http", "mailto:")):
            continue
        if not (DOCS / target).resolve().exists():
            dead.append(target)
    assert not dead, f"docs/README.md links to nonexistent files: {dead}"


def test_asset_dirs_are_mentioned() -> None:
    """Asset folders are covered at folder level, not silently omitted."""
    index = _index_text()
    for asset_dir in ASSET_DIRS:
        assert f"{asset_dir}/" in index, (
            f"docs/README.md must mention the asset folder '{asset_dir}/'"
        )
