from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_build_runtime_pack():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "datasets"
        / "remora_knowledge_v1"
        / "scripts"
        / "build_runtime_evidence_pack.py"
    )
    spec = importlib.util.spec_from_file_location("build_runtime_evidence_pack", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_runtime_pack


build_runtime_pack = _load_build_runtime_pack()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_build_runtime_pack_merges_base_and_live_feeds(tmp_path: Path) -> None:
    base = tmp_path / "evidence_objects.jsonl"
    live_root = tmp_path / "live_feeds"
    out = tmp_path / "runtime_evidence_objects.jsonl"

    _write_jsonl(
        base,
        [
            {"evidence_id": "ev_a", "source": "base"},
            {"evidence_id": "ev_b", "source": "base"},
        ],
    )
    _write_jsonl(
        live_root / "nvd" / "cves.normalized.jsonl",
        [
            {"evidence_id": "ev_c", "source": "nvd"},
        ],
    )

    stats = build_runtime_pack(base_path=base, live_feeds_root=live_root, out_path=out)

    assert stats["base_rows"] == 2
    assert stats["feed_files"] == 1
    assert stats["feed_rows"] == 1
    assert stats["merged_rows"] == 3

    with out.open("r", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    ids = {row["evidence_id"] for row in rows}
    assert ids == {"ev_a", "ev_b", "ev_c"}


def test_build_runtime_pack_prefers_latest_row_for_same_evidence_id(tmp_path: Path) -> None:
    base = tmp_path / "evidence_objects.jsonl"
    live_root = tmp_path / "live_feeds"
    out = tmp_path / "runtime_evidence_objects.jsonl"

    _write_jsonl(
        base,
        [
            {"evidence_id": "ev_dup", "source": "base", "value": 1},
        ],
    )
    _write_jsonl(
        live_root / "kev" / "kev.normalized.jsonl",
        [
            {"evidence_id": "ev_dup", "source": "live", "value": 2},
        ],
    )

    stats = build_runtime_pack(base_path=base, live_feeds_root=live_root, out_path=out)
    assert stats["merged_rows"] == 1

    with out.open("r", encoding="utf-8") as handle:
        row = json.loads(handle.readline())
    assert row["source"] == "live"
    assert row["value"] == 2
