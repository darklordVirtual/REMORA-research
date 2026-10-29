# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""CI gate (SR-11 / SR-23, SEC-19): Python installs in workflows must be
hash-pinned, and the hashed lock files must carry a hash on every package.

Scope: every ``run:`` script in ``.github/workflows/*.y*ml`` and in composite
actions under ``.github/actions/**/action.y*ml``, and every
``requirements-*.lock`` at the repository root.

How a ``run:`` script is read:
  * backslash continuations are joined into one logical line;
  * the logical line is tokenised with shell quoting rules (comments dropped)
    and split into commands on ``&&``, ``||``, ``;``, ``|``, ``(``, ``)`` and
    redirections, so ``-e . && pip install evil`` is two commands;
  * ``bash -c``/``sh -c``/``eval`` arguments are read as scripts in turn, and
    a ``python -c`` program that mentions an install is reported as opaque;
  * a marker (``# hash-exempt: <reason>`` or ``# pinned: <reason>``) counts
    only in the block of full-line comments immediately above the command,
    inside the same ``run:`` script, and only when that logical line holds a
    single installer command. YAML comments outside the script, comments in
    other steps and trailing comments on continuation lines do not count.

Installer commands recognised: ``pip``/``pip3``/``pip3.12`` (any path),
``python[3[.x]] -m pip``, ``uv pip install|sync``, ``uv add``, ``uv tool
install|run``, ``uv run --with``, ``uvx``, ``pipx install|run|inject`` and
``poetry add``.

A pip / uv pip install passes when ONE of these holds:
  1. it carries the ``--require-hashes`` option token and at least one
     ``-r``/``--requirement`` file (pip then rejects any unhashed input);
  2. it carries a ``-c``/``--constraint`` file (version-constrained; the
     weaker, documented tier for jobs that publish nothing);
  3. every target is in-repository code (``.``, ``./path``, a ``$VAR`` path,
     a local wheel), it uses ``--no-deps``, and it either uses
     ``--no-build-isolation`` or installs only ``.whl`` files, so neither
     dependencies nor a build backend are resolved from the index;
  4. every target is an exact ``name==version`` pin and a ``# pinned:``
     marker gives the reason it is not hashed;
  5. a ``# hash-exempt:`` marker gives the reason.
The other installers (uvx, pipx, poetry add, uv tool, uv add, uv run --with)
never hash-pin and pass only with ``# hash-exempt:``.

Exits non-zero with every violation listed.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
from collections.abc import Iterator
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")
_PKG_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9,._-]+\])?==\S+")
_EXEMPT = re.compile(r"^#\s*hash-exempt:\s*\S", re.IGNORECASE)
_PINNED = re.compile(r"^#\s*pinned:\s*\S", re.IGNORECASE)
_EXACT_PIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?==[A-Za-z0-9.+!_-]+$")
_PIP_EXE = re.compile(r"^pip(\d+(\.\d+)?)?$")
_PY_EXE = re.compile(r"^python(\d+(\.\d+)?)?$")
_SHELLS = {"bash", "sh", "zsh", "dash"}
# Regex fallback for text the tokenizer cannot read (and python -c bodies).
_INSTALL_HINT = re.compile(
    r"\b(pip\d*(\.\d+)?|uv\s+pip|-m\s+pip)\s+(install|sync|wheel)\b|\buvx\b|"
    r"\bpipx\s+(install|run|inject)\b|\bpoetry\s+add\b|\buv\s+(tool|add)\b"
)
# Inside a python -c program the install is usually spelled as an argv list.
_PY_INSTALL_HINT = re.compile(r"ensurepip|\bpip\w*\W+install\b|\bpip\.main\b")
_PUNCT = set("();<>|&")
_WRAPPERS = {"then", "do", "else", "elif", "if", "while", "until", "!", "time",
             "sudo", "exec", "{", "}", "command", "nohup", "xargs"}
# pip / uv pip options that take a separate value token.
_VALUE_OPTS = {
    "-r", "--requirement", "-c", "--constraint", "-e", "--editable",
    "-i", "--index-url", "--extra-index-url", "-f", "--find-links",
    "-t", "--target", "--prefix", "--root", "--python-version", "--platform",
    "--implementation", "--abi", "--only-binary", "--no-binary",
    "--progress-bar", "--log", "--cache-dir", "--src", "--upgrade-strategy",
    "--trusted-host", "--python", "-p", "-C", "--config-settings",
    "--global-option", "--report", "--root-user-action", "--keyring-provider",
    "--proxy", "--retries", "--timeout", "--exists-action", "--cert",
    "--client-cert", "--group", "-w", "--wheel-dir", "--extra",
    "--override", "--index", "--default-index", "--index-strategy",
}


def _logical_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Join backslash continuations so a multi-line command is judged whole."""
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        start, text = i, lines[i]
        while text.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            text = text.rstrip()[:-1] + " " + lines[i].strip()
        out.append((start, text))
        i += 1
    return out


def _tokens(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    return list(lexer)


def _commands(tokens: list[str]) -> Iterator[list[str]]:
    current: list[str] = []
    for tok in tokens:
        if tok and set(tok) <= _PUNCT:
            if current:
                yield current
            current = []
            continue
        current.append(tok.strip("`"))
    if current:
        yield current


def _strip_wrappers(argv: list[str]) -> list[str]:
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in _WRAPPERS or tok == "$" or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            i += 1
            continue
        if tok == "env":
            i += 1
            while i < len(argv) and (argv[i].startswith("-") or "=" in argv[i]):
                i += 1
            continue
        break
    return argv[i:]


def _base(tok: str) -> str:
    return tok.rsplit("/", 1)[-1]


def _classify(argv: list[str]) -> tuple[str, list[str]] | None:
    """Return (kind, args-after-subcommand) for an installer command."""
    if not argv:
        return None
    exe = _base(argv[0])
    rest = argv[1:]
    if _PY_EXE.match(exe):
        j = 0
        while j < len(rest) and rest[j].startswith("-") and rest[j] != "-m":
            j += 1
        if j + 1 < len(rest) and rest[j] == "-m" and _PIP_EXE.match(rest[j + 1]):
            rest = rest[j + 2:]
            exe = "pip"
        else:
            return None
    if _PIP_EXE.match(exe):
        sub = [t for t in rest if not t.startswith("-")][:1]
        if sub and sub[0] in ("install", "wheel"):
            return "pip", rest[rest.index(sub[0]) + 1:]
        return None
    if exe == "uv" and rest:
        if rest[0] == "pip" and len(rest) > 1 and rest[1] in ("install", "sync"):
            return "pip", rest[2:]
        if rest[0] == "add" or (rest[0] == "tool" and len(rest) > 1
                                and rest[1] in ("install", "run")):
            return "tool", rest
        if rest[0] == "run" and any(t == "--with" or t.startswith("--with=") for t in rest):
            return "tool", rest
        return None
    if exe == "uvx":
        return "tool", rest
    if exe == "pipx" and rest and rest[0] in ("install", "run", "inject", "upgrade"):
        return "tool", rest
    if exe == "poetry" and rest and rest[0] == "add":
        return "tool", rest
    return None


def _is_local(target: str) -> bool:
    t = target.split("[", 1)[0] if not target.startswith("$(") else target
    if "://" in t or t.startswith("git+"):
        return False
    return t in (".", "..") or t.startswith(("./", "../", "/", "~", "$")) or "/" in t


def _judge_pip(args: list[str], markers: set[str]) -> str | None:
    opts: set[str] = set()
    req_files: list[str] = []
    constraint_files: list[str] = []
    targets: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("--") and "=" in tok:
            name, value = tok.split("=", 1)
            if name == "--requirement":
                req_files.append(value)
            elif name == "--constraint":
                constraint_files.append(value)
            elif name == "--editable":
                targets.append(value)
            opts.add(name)
            i += 1
            continue
        if tok in _VALUE_OPTS:
            value = args[i + 1] if i + 1 < len(args) else ""
            if tok in ("-r", "--requirement"):
                req_files.append(value)
            elif tok in ("-c", "--constraint"):
                constraint_files.append(value)
            elif tok in ("-e", "--editable"):
                targets.append(value)
            opts.add(tok)
            i += 2
            continue
        if re.match(r"^-[rce].+", tok):  # -rfile / -cfile / -e.
            {"r": req_files, "c": constraint_files, "e": targets}[tok[1]].append(tok[2:])
            i += 1
            continue
        if tok.startswith("-"):
            opts.add(tok)
            i += 1
            continue
        targets.append(tok)
        i += 1

    if "hash-exempt" in markers:
        return None
    if "--require-hashes" in opts and req_files:
        return None
    if constraint_files and all(constraint_files):
        return None
    if targets and not req_files and all(_is_local(t) for t in targets):
        wheels_only = all(t.split("[", 1)[0].endswith(".whl") for t in targets)
        if "--no-deps" not in opts:
            return ("installs in-repository code without --no-deps, so its "
                    "dependencies resolve from the index unhashed")
        if "--no-build-isolation" not in opts and not wheels_only:
            return ("builds in-repository code with build isolation, so the "
                    "build backend resolves from the index unhashed (use "
                    "--no-build-isolation with a hashed backend)")
        return None
    if targets and not req_files and all(_EXACT_PIN.match(t) for t in targets):
        if "pinned" in markers:
            return None
        return "version-pinned but unhashed and unmarked direct install"
    return "pip install without --require-hashes -r, a -c constraints file, or a marker"


def _check_script(script: str, where: str, problems: list[str], depth: int = 0) -> None:
    raw = script.splitlines()
    comments: list[str] = []
    for start, text in _logical_lines(raw):
        stripped = text.strip()
        if stripped.startswith("#"):
            comments.append(stripped)
            continue
        block, comments = comments, []
        if not stripped:
            continue
        try:
            tokens = _tokens(text)
        except ValueError:
            if _INSTALL_HINT.search(text):
                problems.append(f"{where}:{start + 1}: unparseable line mentions an install")
            continue
        found: list[tuple[str, list[str]]] = []
        for argv in _commands(tokens):
            argv = _strip_wrappers(argv)
            if not argv:
                continue
            exe = _base(argv[0])
            if (exe in _SHELLS and "-c" in argv) or exe == "eval":
                body = argv[argv.index("-c") + 1] if exe != "eval" else " ".join(argv[1:])
                if depth < 3:
                    _check_script(body, f"{where}:{start + 1}", problems, depth + 1)
                continue
            if _PY_EXE.match(exe) and "-c" in argv:
                body = argv[argv.index("-c") + 1] if argv.index("-c") + 1 < len(argv) else ""
                if _INSTALL_HINT.search(body) or _PY_INSTALL_HINT.search(body):
                    found.append(("opaque", argv))
                continue
            kind = _classify(argv)
            if kind:
                found.append(kind)
        if not found:
            continue
        markers: set[str] = set()
        if len(found) == 1:
            for line in block:
                if _EXEMPT.match(line):
                    markers.add("hash-exempt")
                if _PINNED.match(line):
                    markers.add("pinned")
        for kind, args in found:
            if kind == "pip":
                problem = _judge_pip(args, markers)
            elif kind == "opaque":
                problem = (None if "hash-exempt" in markers else
                           "python -c program performs an install the gate cannot read")
            else:
                problem = (None if "hash-exempt" in markers else
                           f"{_base(args[0]) if args else 'tool'} installer never "
                           "hash-pins; needs a # hash-exempt: marker")
            if problem:
                problems.append(f"{where}:{start + 1}: {problem}")


def _run_blocks(doc: object) -> Iterator[str]:
    """Every `run:` string in a workflow or composite action document."""
    if not isinstance(doc, dict):
        return
    steps: list = []
    for job in (doc.get("jobs") or {}).values():
        if isinstance(job, dict):
            steps.extend(job.get("steps") or [])
    runs = doc.get("runs")
    if isinstance(runs, dict):
        steps.extend(runs.get("steps") or [])
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("run"), str):
            yield step["run"]


def _script_files() -> list[Path]:
    gh = ROOT / ".github"
    files = sorted((gh / "workflows").glob("*.yml")) + sorted((gh / "workflows").glob("*.yaml"))
    files += sorted(gh.glob("actions/**/action.yml")) + sorted(gh.glob("actions/**/action.yaml"))
    return files


def _check_workflows() -> list[str]:
    problems: list[str] = []
    for path in _script_files():
        rel = path.relative_to(ROOT).as_posix()
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            problems.append(f"{rel}: unparseable YAML ({exc.__class__.__name__})")
            continue
        for n, script in enumerate(_run_blocks(doc)):
            _check_script(script, f"{rel}[run {n + 1}]", problems)
    return problems


def _hashed_locks() -> list[str]:
    return sorted(p.name for p in ROOT.glob("requirements-*.lock"))


def _check_lock(name: str) -> list[str]:
    path = ROOT / name
    problems: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = _PKG_LINE.match(line)
        if match:
            block = [line]
            while block[-1].endswith("\\") and i + 1 < len(lines):
                i += 1
                block.append(lines[i].strip())
            if not any(_HASH.search(b) for b in block):
                problems.append(f"{name}:{i + 1}: {match.group(1)} has no sha256 hash")
        elif line and not line.startswith("#") and not line.startswith("--hash"):
            problems.append(f"{name}:{i + 1}: not an exact pin: {line[:60]}")
        i += 1
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", help="repo root to check (default: script's)")
    args = parser.parse_args(argv)

    global ROOT
    if args.root:
        ROOT = Path(os.path.abspath(args.root))

    problems = _check_workflows()
    locks = _hashed_locks()
    if not locks:
        problems.append("no requirements-*.lock found")
    for name in locks:
        problems.extend(_check_lock(name))
    if problems:
        print("[FAIL] hash-pinning gate:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"[OK] every workflow install is hash-pinned, constrained, in-repo "
          f"without resolution, or marked with a reason; {len(locks)} hashed "
          f"lock(s) carry sha256 on every package: {', '.join(locks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
