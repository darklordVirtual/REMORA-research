# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The provenance register (legal/PROVENANCE.md): reproducible, and able to see a renamed copy."""
from __future__ import annotations

import importlib.util
import io
import json
import keyword
import re
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("provenance_register", ROOT / "scripts" / "provenance_register.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PR = _load()
REGISTER = json.loads((ROOT / "docs" / "assurance" / "provenance_register_v1.json").read_text(encoding="utf-8"))


def _rename_everything(source: str) -> str:
    """Every identifier renamed, every comment and docstring changed: a disguised copy."""
    names: dict[str, str] = {}
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        text = tok.string
        if tok.type == tokenize.NAME and not keyword.iskeyword(text):
            text = names.setdefault(text, f"renamed_{len(names)}")
        elif tok.type == tokenize.STRING:
            text = repr("different text")
        elif tok.type == tokenize.COMMENT:
            text = "# rewritten"
        out.append((tok.type, text))
    return tokenize.untokenize(out)


def test_register_is_internally_consistent() -> None:
    body = {k: v for k, v in REGISTER.items() if k != "register_sha256"}
    import hashlib

    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert digest == REGISTER["register_sha256"]
    for concept in REGISTER["concepts"]:
        assert all(first["found"] for first in concept["first"]), concept["id"]
        for first in concept["first"]:
            assert re.fullmatch(r"[0-9a-f]{40}", first["commit"]), concept["id"]
    for module, entry in REGISTER["modules"].items():
        assert entry["fingerprints"], module


def test_a_renamed_copy_is_found_and_an_unrelated_module_is_not(tmp_path: Path) -> None:
    snapshot = REGISTER["snapshot"]
    lease = subprocess.run(["git", "show", f"{snapshot}:remora/enforcement/lease.py"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", check=True).stdout
    (tmp_path / "copied").mkdir()
    (tmp_path / "copied" / "permits.py").write_text(_rename_everything(lease), encoding="utf-8")
    (tmp_path / "unrelated").mkdir()
    (tmp_path / "unrelated" / "cli.py").write_text((ROOT / "remora" / "cli.py").read_text(encoding="utf-8"), encoding="utf-8")
    rows = {r["module"]: r for r in PR.compare(tmp_path / "copied", REGISTER, 0.25)}
    assert rows["remora/enforcement/lease.py"]["share_in_best_file"] > 0.9
    assert rows["remora/enforcement/lease.py"]["flag"]
    unrelated = {r["module"]: r for r in PR.compare(tmp_path / "unrelated", REGISTER, 0.25)}
    # Same author, same idioms: measured at 0.14, under the flag. Third-party code measured at most 0.158.
    assert not any(r["flag"] for r in unrelated.values())


def test_fingerprints_ignore_formatting_and_comments() -> None:
    a = "def f(x):\n    return x + 1  # one\n" * 6
    b = "def g(y):\n\n    # a comment\n    return y + 1\n" * 6
    assert PR.fingerprints(a) == PR.fingerprints(b)


@pytest.mark.slow
def test_register_reproduces_from_git_history() -> None:
    assert PR.render(PR.build()) == (ROOT / "docs" / "assurance" / "provenance_register_v1.json").read_text(encoding="utf-8")
