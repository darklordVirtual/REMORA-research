# Author: Stian Skogbrott
# License: Apache-2.0
"""Research-control matrix integrity.

The matrix is the machine-checked research -> code -> test chain. Its value is
that it cannot drift: every referenced path must exist, the rendered view must
be current, and the registered lines must cover the numbered sections of
docs/09-related-work.md.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "research" / "research_control_matrix_v1.yaml"
GENERATED = ROOT / "docs" / "research" / "research_control_matrix.generated.md"
SCRIPT = ROOT / "scripts" / "generate_research_control_matrix.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("gen_rcm", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _data() -> dict:
    with open(REGISTER, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_register_parses_and_validates() -> None:
    mod = _load_module()
    errors = mod.validate(_data())
    assert errors == [], errors


def test_every_code_and_test_path_exists() -> None:
    data = _data()
    for e in data["entries"]:
        for path in list(e.get("code", []) or []) + list(e.get("tests", []) or []):
            assert (ROOT / path).exists(), f"{e['id']}: missing {path}"


def test_generated_view_is_up_to_date() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr


def test_implemented_lines_have_tests() -> None:
    """Anything claimed implemented_and_tested must actually cite tests."""
    for e in _data()["entries"]:
        if e["maturity"] == "implemented_and_tested":
            assert e.get("tests"), f"{e['id']} is implemented_and_tested but lists no tests"


def test_covers_related_work_sections() -> None:
    """One matrix entry per numbered section of the related-work doc."""
    related = (ROOT / "docs" / "09-related-work.md").read_text(encoding="utf-8")
    section_nums = set(re.findall(r"^## (\d+)\.", related, flags=re.MULTILINE))
    cited = set()
    for e in _data()["entries"]:
        m = re.search(r"§(\d+)", e["related_work_section"])
        if m:
            cited.add(m.group(1))
    assert section_nums <= cited, f"related-work sections not in matrix: {section_nums - cited}"
