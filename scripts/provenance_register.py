#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Provenance register: when REMORA's distinctive concepts first appeared, and fingerprints of its code.

Two records, both reproducible from git history alone (legal/PROVENANCE.md):

1. For every term in ``docs/assurance/provenance_concepts_v1.yaml``, the first
   commit on the snapshot's history that introduced it (``git log -S``), with
   author date, committer date and signature status. Signed commits pushed to
   GitHub give a third party a dated record to check.
2. For every listed module, winnowing fingerprints of its token stream at the
   snapshot commit (Schleimer, Wilkerson and Aiken, 2003, the method behind
   MOSS). Identifiers become ``V``, strings ``S`` and numbers ``N`` before
   hashing, so renaming classes and variables does not hide a copy, while
   formatting and comments are ignored.

``--compare DIR`` fingerprints the Python files under another directory, for
example a local clone, and reports for each REMORA module how much of its
fingerprint appears there. A high share says the code structure is shared; it
does not say who copied whom, which the dated records of part 1 and the other
side's own history have to settle.

Usage::

    python scripts/provenance_register.py --write           # build docs/assurance/provenance_register_v1.json
    python scripts/provenance_register.py --check           # rebuild in memory and compare
    python scripts/provenance_register.py --compare ../other-clone [--min-share 0.25]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import keyword
import subprocess
import sys
import tokenize
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONCEPTS = ROOT / "docs" / "assurance" / "provenance_concepts_v1.yaml"
REGISTER = ROOT / "docs" / "assurance" / "provenance_register_v1.json"

#: k-gram length in normalised tokens, and the winnowing window. Any shared run of
#: at least K + W - 1 tokens is guaranteed to produce a shared fingerprint.
K = 12
W = 8
_SKIP = {tokenize.COMMENT, tokenize.NL, tokenize.ENCODING, tokenize.ENDMARKER}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def normalised_tokens(source: str) -> list[str]:
    """The token stream with identifiers, strings and numbers reduced to their kind."""
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in _SKIP:
                continue
            if tok.type == tokenize.NAME:
                out.append(tok.string if keyword.iskeyword(tok.string) else "V")
            elif tok.type == tokenize.STRING:
                out.append("S")
            elif tok.type == tokenize.NUMBER:
                out.append("N")
            elif tok.type == tokenize.NEWLINE:
                out.append(";")
            elif tok.type == tokenize.INDENT:
                out.append("{")
            elif tok.type == tokenize.DEDENT:
                out.append("}")
            else:
                out.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A file that does not tokenise to the end still has a usable prefix;
        # fingerprint what was read rather than dropping the file.
        return out
    return out


def fingerprints(source: str, k: int = K, w: int = W) -> list[str]:
    """Winnowed k-gram hashes of the normalised token stream, as sorted hex strings."""
    tokens = normalised_tokens(source)
    grams = [hashlib.sha1(" ".join(tokens[i:i + k]).encode("utf-8")).hexdigest()[:16]
             for i in range(len(tokens) - k + 1)]
    chosen: set[str] = set()
    for i in range(max(0, len(grams) - w + 1)):
        chosen.add(min(grams[i:i + w]))
    if grams and len(grams) < w:
        chosen.add(min(grams))
    return sorted(chosen)


def first_introduction(term: str, snapshot: str) -> dict:
    """The first commit in the snapshot's history whose diff adds the term."""
    out = _git("log", "--reverse", "--format=%H%x09%aI%x09%cI%x09%G?%x09%s", f"-S{term}", snapshot)
    line = next((ln for ln in out.splitlines() if ln.strip()), "")
    if not line:
        return {"term": term, "found": False}
    sha, authored, committed, signature, subject = line.split("\t", 4)
    return {"term": term, "found": True, "commit": sha, "authored": authored, "committed": committed,
            "signature": signature, "subject": subject}


def build() -> dict:
    spec = yaml.safe_load(CONCEPTS.read_text(encoding="utf-8"))
    snapshot = spec["snapshot"]
    concepts = []
    for concept in spec["concepts"]:
        concepts.append({"id": concept["id"], "name": concept["name"],
                         "first": [first_introduction(t, snapshot) for t in concept["terms"]]})
    modules = {}
    for path in spec["fingerprint_modules"]:
        source = _git("show", f"{snapshot}:{path}")
        modules[path] = {
            "sha256": hashlib.sha256(source.replace("\r\n", "\n").encode("utf-8")).hexdigest(),
            "tokens": len(normalised_tokens(source)),
            "fingerprints": fingerprints(source),
        }
    register = {
        "schema": "provenance_register_v1",
        "snapshot": snapshot,
        "snapshot_committed": _git("show", "-s", "--format=%cI", snapshot).strip(),
        "method": {"fingerprint": "winnowing over normalised Python tokens", "k": K, "window": W},
        "concepts": concepts,
        "modules": modules,
    }
    body = json.dumps(register, sort_keys=True, separators=(",", ":"))
    register["register_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return register


def render(register: dict) -> str:
    return json.dumps(register, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def compare(directory: Path, register: dict, min_share: float) -> list[dict]:
    """For each REMORA module, the share of its fingerprints found in any Python file under ``directory``."""
    theirs: dict[str, set[str]] = {}
    for path in sorted(directory.rglob("*.py")):
        try:
            theirs[str(path.relative_to(directory))] = set(fingerprints(path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    union = set().union(*theirs.values()) if theirs else set()
    rows = []
    for module, entry in register["modules"].items():
        ours = set(entry["fingerprints"])
        if not ours:
            continue
        best_file, best = "", 0.0
        for name, prints in theirs.items():
            share = len(ours & prints) / len(ours)
            if share > best:
                best_file, best = name, share
        rows.append({"module": module, "share_anywhere": round(len(ours & union) / len(ours), 3),
                     "best_file": best_file, "share_in_best_file": round(best, 3),
                     "flag": best >= min_share})
    return rows


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="write the register")
    parser.add_argument("--check", action="store_true", help="fail if the committed register differs from a rebuild")
    parser.add_argument("--compare", type=Path, help="a directory of Python code to measure against the register")
    parser.add_argument("--min-share", type=float, default=0.25, help="share in one file that is flagged")
    args = parser.parse_args(argv)
    if args.compare:
        register = json.loads(REGISTER.read_text(encoding="utf-8"))
        rows = compare(args.compare, register, args.min_share)
        for row in sorted(rows, key=lambda r: -r["share_in_best_file"]):
            mark = "FLAG" if row["flag"] else "    "
            print(f"{mark} {row['share_in_best_file']:6.1%} {row['module']:48} best: {row['best_file']} "
                  f"(anywhere {row['share_anywhere']:.1%})")
        return 0
    register = build()
    if args.write:
        REGISTER.write_text(render(register), encoding="utf-8", newline="\n")
        print(f"wrote {REGISTER.relative_to(ROOT)} (register_sha256 {register['register_sha256']})")
        return 0
    if args.check:
        current = REGISTER.read_text(encoding="utf-8") if REGISTER.exists() else ""
        if current != render(register):
            print("provenance register is stale: run scripts/provenance_register.py --write", file=sys.stderr)
            return 1
        print(f"provenance register reproduces (register_sha256 {register['register_sha256']})")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
