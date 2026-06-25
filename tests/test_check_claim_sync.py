from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_check_claim_sync():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "check_claim_sync.py"
    spec = importlib.util.spec_from_file_location("check_claim_sync", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_claim_sync = _load_check_claim_sync()


def test_check_file_requires_governance_overlay_phrase(tmp_path: Path) -> None:
    p = tmp_path / "doc.md"
    p.write_text("This is a benchmark note only.\n", encoding="utf-8")

    errors = check_claim_sync._check_file(p)
    assert any("governance overlay" in e for e in errors)


def test_check_file_requires_qualifier_for_risky_claim(tmp_path: Path) -> None:
    p = tmp_path / "doc.md"
    p.write_text(
        "REMORA is a governance overlay.\n"
        "We achieved 0% unsafe execution.\n",
        encoding="utf-8",
    )

    errors = check_claim_sync._check_file(p)
    assert any("missing benchmark qualifier" in e for e in errors)


def test_check_file_accepts_qualified_risky_claim(tmp_path: Path) -> None:
    p = tmp_path / "doc.md"
    p.write_text(
        "REMORA is a governance overlay.\n"
        "We achieved 0% unsafe execution in benchmark replay.\n",
        encoding="utf-8",
    )

    errors = check_claim_sync._check_file(p)
    assert errors == []
