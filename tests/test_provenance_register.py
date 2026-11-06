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
import textwrap
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

#: Both history tests read the snapshot commit, which a shallow CI checkout does not hold. The
#: verify job checks out full history, so they still run on every push there.
needs_history = pytest.mark.skipif(
    subprocess.run(["git", "cat-file", "-e", f"{REGISTER['snapshot']}^{{commit}}"], cwd=ROOT,
                   capture_output=True, check=False).returncode != 0,
    reason="the register's snapshot commit is not in this (shallow) clone",
)


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
        assert concept.get("invariant"), concept["id"]
        assert all(first["found"] for first in concept["first"]), concept["id"]
        for first in concept["first"]:
            assert first["term"] != "regate"
            assert re.fullmatch(r"[0-9a-f]{40}", first["commit"]), concept["id"]
            assert first["paths"] and first["path_count"] >= len(first["paths"])
    assert len(REGISTER["markers"]) >= 2
    for module, entry in REGISTER["modules"].items():
        assert entry["fingerprints"], module


@needs_history
def test_a_renamed_copy_is_found_and_an_unrelated_module_is_not(tmp_path: Path) -> None:
    snapshot = REGISTER["snapshot"]
    lease = subprocess.run(["git", "show", f"{snapshot}:remora/enforcement/lease.py"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", check=True).stdout
    (tmp_path / "copied").mkdir()
    (tmp_path / "copied" / "permits.py").write_text(_rename_everything(lease), encoding="utf-8")
    (tmp_path / "unrelated").mkdir()
    (tmp_path / "unrelated" / "cli.py").write_text((ROOT / "remora" / "cli.py").read_text(encoding="utf-8"), encoding="utf-8")
    rows = {r["module"]: r for r in PR.compare(tmp_path / "copied", REGISTER, 0.25)["modules"]}
    assert rows["remora/enforcement/lease.py"]["share_in_best_file"] > 0.9
    assert rows["remora/enforcement/lease.py"]["flag"]
    unrelated = {r["module"]: r for r in PR.compare(tmp_path / "unrelated", REGISTER, 0.25)["modules"]}
    # Same author, same idioms: measured at 0.14, under the flag. Third-party code measured at most 0.158.
    assert not any(r["flag"] or r["flag_cover"] for r in unrelated.values())


def test_a_term_inside_a_longer_token_does_not_count() -> None:
    assert re.search(PR.term_pattern("regate"), "aggregate") is None
    assert re.search(PR.term_pattern("regate"), "the regate step")
    assert re.search(PR.term_pattern("ToolSpec"), "ToolSpecification") is None


def test_two_coined_identifiers_are_flagged_and_one_is_not(tmp_path: Path) -> None:
    register = {"modules": {}, "markers": ["PolicyDecisionToken", "ExecutionLease", "NonceLedger"]}
    one = tmp_path / "one"
    one.mkdir()
    (one / "a.py").write_text("token = 'PolicyDecisionToken'\n", encoding="utf-8")
    single = PR.compare(one, register, 0.25)
    assert [hit["marker"] for hit in single["markers"]] == ["PolicyDecisionToken"]
    assert not single["marker_flag"]
    two = tmp_path / "two"
    two.mkdir()
    (two / "notes.md").write_text("Uses PolicyDecisionToken and ExecutionLease.\n", encoding="utf-8")
    paired = PR.compare(two, register, 0.25)
    assert paired["marker_flag"]
    assert {hit["marker"] for hit in paired["markers"]} == {"PolicyDecisionToken", "ExecutionLease"}


def _halves(body: str) -> list[str]:
    """A method over forty lines cut at the blank line nearest its middle, when
    both halves still tokenize; otherwise the method whole."""
    lines = body.splitlines(keepends=True)
    if len(lines) <= 40:
        return [body]
    blanks = [i for i, line in enumerate(lines) if not line.strip() and 0 < i < len(lines) - 1]
    if not blanks:
        return [body]
    cut = min(blanks, key=lambda i: abs(i - len(lines) // 2))
    halves = ["".join(lines[:cut]), "".join(lines[cut:])]
    try:
        for half in halves:
            list(tokenize.generate_tokens(io.StringIO(textwrap.dedent(half)).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return [body]
    return halves


@needs_history
def test_a_renamed_copy_split_across_files_is_still_flagged(tmp_path: Path) -> None:
    snapshot = REGISTER["snapshot"]
    lease = subprocess.run(["git", "show", f"{snapshot}:remora/enforcement/lease.py"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", check=True).stdout
    # One renamed file per method, and a method longer than forty lines cut in
    # two, as someone extracting helpers would. The two large classes would
    # otherwise keep more than 25 % in a single file: at snapshot 0b595b8c the
    # per-method split measured 20.1 % in one file and 59.6 % across the eight
    # files that cover the most; at b9865d32 one method alone reached 25.0 %,
    # which is the single-file threshold and would make the test measure the
    # file's growth rather than the cover rule.
    chunks = [part for part in re.split(r"(?=^(?:def |class |async def ))", lease, flags=re.M) if part.strip()]
    dest = tmp_path / "split"
    dest.mkdir()
    n = 0
    for chunk in chunks:
        for method in re.split(r"(?=^    def )", chunk, flags=re.M):
            body = textwrap.dedent(method)
            if not body.strip():
                continue
            for half in _halves(body):
                (dest / f"part_{n}.py").write_text(_rename_everything(half), encoding="utf-8")
                n += 1
    row = next(r for r in PR.compare(dest, REGISTER, 0.25, 0.50)["modules"]
               if r["module"] == "remora/enforcement/lease.py")
    assert row["share_in_best_file"] < 0.25
    assert row["share_in_best_eight"] >= 0.50
    assert row["flag_cover"]
    assert not row["flag"]


def test_fingerprints_ignore_formatting_and_comments() -> None:
    a = "def f(x):\n    return x + 1  # one\n" * 6
    b = "def g(y):\n\n    # a comment\n    return y + 1\n" * 6
    assert PR.fingerprints(a) == PR.fingerprints(b)


def test_an_f_string_is_one_string_token_on_every_interpreter() -> None:
    """Python 3.12 (PEP 701) splits an f-string into start, middle and end
    tokens with the replacement fields' own tokens between them; 3.11 yields
    one STRING. The register must fingerprint identically on both, or the
    committed register reproduces on one interpreter and not another (the
    3.11 leg of the full suite failed this way on 2026-10-24)."""
    plain = 'x = "a"\n'
    formatted = 'x = f"a {b!r:>{w}} {c[0]} d"\n'
    assert PR.normalised_tokens(plain) == ["V", "=", "S", ";"]
    assert PR.normalised_tokens(formatted) == PR.normalised_tokens(plain)
    assert PR.fingerprints(formatted * 4) == PR.fingerprints(plain * 4)
    # a run inside a call keeps the tokens around it
    assert PR.normalised_tokens('f(f"{x}", 1)\n') == ["V", "(", "S", ",", "N", ")", ";"]


def test_signature_status_reads_the_commit_object_not_the_local_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """%G? said E with gpg and N without it for the same commit; the gpgsig header says the same everywhere."""
    signed = ("tree 0\nparent 1\nauthor a <a> 0 +0000\ncommitter a <a> 0 +0000\n"
              "gpgsig -----BEGIN SSH SIGNATURE-----\n xyz\n -----END SSH SIGNATURE-----\n\nsubject\n")
    unsigned = "tree 0\nauthor a <a> 0 +0000\ncommitter a <a> 0 +0000\n\nsubject\n\ngpgsig in the message body\n"
    objects = {"s": signed, "u": unsigned, "s256": signed.replace("gpgsig ", "gpgsig-sha256 ")}
    monkeypatch.setattr(PR, "_git", lambda *args, **kw: subprocess.CompletedProcess(args, 0, objects[args[-1]], ""))
    assert PR.signature_status("s") == "E"
    assert PR.signature_status("s256") == "E"
    assert PR.signature_status("u") == "N"


@needs_history
def test_recorded_signature_status_matches_the_commit_objects() -> None:
    for concept in REGISTER["concepts"]:
        for first in concept["first"]:
            assert PR.signature_status(first["commit"]) == first["signature"], (concept["id"], first["term"])


@needs_history
@pytest.mark.slow
def test_register_reproduces_from_git_history() -> None:
    assert PR.render(PR.build()) == (ROOT / "docs" / "assurance" / "provenance_register_v1.json").read_text(encoding="utf-8")
