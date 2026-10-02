#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Provenance register: when REMORA's distinctive concepts first appeared, and fingerprints of its code.

Three records, all reproducible from the pinned inputs (legal/PROVENANCE.md):

1. For every term in ``docs/assurance/provenance_concepts_v1.yaml``, the first
   commit on the snapshot's history that introduced it as its own token
   (``git log -G`` with a word boundary, not a substring search), with author
   date, committer date, signature status and up to eight paths. A term buried
   inside a longer token, such as ``regate`` inside ``aggregate``, does not count.
2. For every listed module, winnowing fingerprints of its token stream at the
   snapshot commit (Schleimer, Wilkerson and Aiken, 2003, the method behind
   MOSS). Identifiers become ``V``, strings ``S`` and numbers ``N`` before
   hashing, so renaming classes and variables does not hide a copy, while
   formatting and comments are ignored.
3. A list of coined identifiers. ``--compare`` reports how many of them appear
   as their own tokens in another tree.

``--compare DIR`` does not say who copied whom, and it does not grant or refuse
a license. Commercial use of REMORA still requires a written commercial license.
A flagged overlap is a reason to read both histories, not a public accusation.

Usage::

    python scripts/provenance_register.py --write
    python scripts/provenance_register.py --check
    python scripts/provenance_register.py --compare ../other-clone [--min-share 0.25]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import keyword
import re
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
_PATH_CAP = 8
_SKIP = {tokenize.COMMENT, tokenize.NL, tokenize.ENCODING, tokenize.ENDMARKER}
_TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".json", ".toml", ".ts", ".js", ".go", ".rs", ".java"}
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
_MAX_MARKER_BYTES = 1_000_000


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--no-pager", *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", check=check,
    )


def term_pattern(term: str) -> str:
    """A term counts only as its own token, not as a substring of a longer one."""
    return r"(^|[^A-Za-z0-9_])" + re.escape(term) + r"($|[^A-Za-z0-9_])"


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
    grams = [
        hashlib.sha1(" ".join(tokens[i:i + k]).encode("utf-8")).hexdigest()[:16]
        for i in range(len(tokens) - k + 1)
    ]
    chosen: set[str] = set()
    for i in range(max(0, len(grams) - w + 1)):
        chosen.add(min(grams[i:i + w]))
    if grams and len(grams) < w:
        chosen.add(min(grams))
    return sorted(chosen)


def introducing_paths(term: str, sha: str) -> list[str]:
    """Sorted paths in ``sha`` whose text contains ``term`` as its own token."""
    proc = _git("grep", "-n", "-I", "-F", "-e", term, sha, check=False)
    if proc.returncode not in (0, 1):
        proc.check_returncode()
    paths: set[str] = set()
    prefix = sha + ":"
    boundary = re.compile(term_pattern(term))
    for line in proc.stdout.splitlines():
        if not line.startswith(prefix):
            continue
        path, _, rest = line[len(prefix):].partition(":")
        _, _, text = rest.partition(":")
        if boundary.search(text):
            paths.add(path)
    return sorted(paths)


def first_introduction(term: str, snapshot: str) -> dict:
    """The first commit in the snapshot's history whose patch adds the term as its own token."""
    proc = _git(
        "log", "--reverse", "--format=%H%x09%aI%x09%cI%x09%G?%x09%s",
        "-G", term_pattern(term), snapshot,
    )
    line = next((ln for ln in proc.stdout.splitlines() if ln.strip()), "")
    if not line:
        return {"term": term, "found": False}
    sha, authored, committed, signature, subject = line.split("\t", 4)
    paths = introducing_paths(term, sha)
    return {
        "term": term, "found": True, "commit": sha, "authored": authored, "committed": committed,
        "signature": signature, "subject": subject, "path_count": len(paths), "paths": paths[:_PATH_CAP],
    }


def build() -> dict:
    spec = yaml.safe_load(CONCEPTS.read_text(encoding="utf-8"))
    snapshot = spec["snapshot"]
    concepts = []
    for concept in spec["concepts"]:
        row = {
            "id": concept["id"],
            "name": concept["name"],
            "first": [first_introduction(t, snapshot) for t in concept["terms"]],
        }
        if concept.get("invariant"):
            row["invariant"] = concept["invariant"].strip()
        concepts.append(row)
    modules = {}
    for path in spec["fingerprint_modules"]:
        source = _git("show", f"{snapshot}:{path}").stdout
        modules[path] = {
            "sha256": hashlib.sha256(source.replace("\r\n", "\n").encode("utf-8")).hexdigest(),
            "tokens": len(normalised_tokens(source)),
            "fingerprints": fingerprints(source),
        }
    register = {
        "schema": "provenance_register_v1",
        "snapshot": snapshot,
        "snapshot_committed": _git("show", "-s", "--format=%cI", snapshot).stdout.strip(),
        "method": {
            "fingerprint": "winnowing over normalised Python tokens",
            "k": K,
            "window": W,
            "term_search": "word-boundary git log -G; a term inside a longer token does not count",
            "paths": "up to 8 sorted paths in the introducing commit",
            "markers": "coined identifiers matched as their own tokens",
            "cover": "share of one module's fingerprints in the files that cover the most of it",
        },
        "concepts": concepts,
        "markers": list(spec.get("markers") or []),
        "modules": modules,
    }
    body = json.dumps(register, sort_keys=True, separators=(",", ":"))
    register["register_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return register


def render(register: dict) -> str:
    return json.dumps(register, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _cover_share(ours: set[str], theirs: dict[str, set[str]], n: int) -> tuple[float, list[str]]:
    """Share of ``ours`` covered by the ``n`` files that add the most remaining fingerprints."""
    if not ours:
        return 0.0, []
    remaining = set(ours)
    pool = dict(theirs)
    chosen: list[str] = []
    for _ in range(n):
        if not remaining or not pool:
            break
        name = max(pool, key=lambda item: len(remaining & pool[item]))
        if not remaining & pool[name]:
            break
        remaining -= pool.pop(name)
        chosen.append(name)
    return 1 - len(remaining) / len(ours), chosen


def python_fingerprints(directory: Path) -> dict[str, set[str]]:
    """Winnowing fingerprints of each Python file under ``directory``."""
    theirs: dict[str, set[str]] = {}
    for path in sorted(directory.rglob("*.py")):
        rel = path.relative_to(directory)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        try:
            theirs[str(rel)] = set(fingerprints(path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return theirs


def marker_hits(directory: Path, markers: list[str]) -> list[dict]:
    """Coined identifiers found as their own tokens."""
    compiled = [(marker, re.compile(term_pattern(marker))) for marker in markers]
    found: dict[str, list[str]] = {marker: [] for marker in markers}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        rel = path.relative_to(directory)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        try:
            if path.stat().st_size > _MAX_MARKER_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel_s = str(rel)
        for marker, pattern in compiled:
            if pattern.search(text):
                found[marker].append(rel_s)
    return [
        {"marker": marker, "file_count": len(paths), "files": paths[:5]}
        for marker, paths in found.items() if paths
    ]


def compare(directory: Path, register: dict, min_share: float, min_cover: float | None = None) -> dict:
    """Fingerprint overlap, split-file cover, and coined-identifier hits under ``directory``.

    ``flag`` on a module is the single-file share. ``flag_cover`` is the share covered by the
    eight files that match it best, which is how a copy split across files shows up. The cover
    threshold is separate because pooling files raises the share against a large unrelated tree.
    """
    cover_at = min_share if min_cover is None else min_cover
    theirs = python_fingerprints(directory)
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
        cover, files = _cover_share(ours, theirs, 8)
        rows.append({
            "module": module,
            "share_anywhere": round(len(ours & union) / len(ours), 3),
            "best_file": best_file,
            "share_in_best_file": round(best, 3),
            "share_in_best_eight": round(cover, 3),
            "best_eight_files": files,
            "flag": best >= min_share,
            "flag_cover": cover >= cover_at,
        })
    hits = marker_hits(directory, list(register.get("markers") or []))
    return {"modules": rows, "markers": hits, "marker_flag": len(hits) >= 2}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="write the register")
    parser.add_argument("--check", action="store_true", help="fail if the committed register differs from a rebuild")
    parser.add_argument("--compare", type=Path, help="a directory of code to measure against the register")
    parser.add_argument("--min-share", type=float, default=0.25, help="share in one file that is flagged")
    parser.add_argument("--min-cover", type=float, default=0.50,
                        help="share across the eight best files that is flagged")
    args = parser.parse_args(argv)
    if args.compare:
        register = json.loads(REGISTER.read_text(encoding="utf-8"))
        report = compare(args.compare, register, args.min_share, args.min_cover)
        print("A flag is overlap with the pinned REMORA register. It is not a finding that anyone copied anything.")
        print("Commercial use of REMORA requires a written commercial license. See legal/LICENSING.md.")
        for row in sorted(report["modules"], key=lambda item: -item["share_in_best_file"]):
            mark = "FLAG" if row["flag"] or row["flag_cover"] else "    "
            print(
                f"{mark} {row['share_in_best_file']:6.1%} {row['module']:48} best: {row['best_file']} "
                f"(eight {row['share_in_best_eight']:.1%}, anywhere {row['share_anywhere']:.1%})"
            )
        if report["markers"]:
            names = ", ".join(hit["marker"] for hit in report["markers"])
            mark = "FLAG" if report["marker_flag"] else "    "
            print(f"{mark} coined identifiers ({len(report['markers'])}): {names}")
        else:
            print("     coined identifiers: none")
        flagged = any(row["flag"] or row["flag_cover"] for row in report["modules"]) or report["marker_flag"]
        return 1 if flagged else 0
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
