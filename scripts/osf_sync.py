#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Mirror the repository onto its OSF project and check that the mirror is exact.

Group (scripts/README.md): gated. ``.github/workflows/osf-sync.yml`` runs
``sync`` and ``verify`` on every push to master and ``verify`` weekly;
``tests/test_osf_sync.py`` runs ``check`` offline.

The OSF project (https://osf.io/5hfae/) holds the tree at one commit, split
into six components. ``LAYOUT`` assigns every tracked file to exactly one
component; a file that matches none, or more than one, fails ``check`` and
every other mode, so a new top-level directory cannot be silently left out of
the archive. Paths inside a component match the repository.

Each component also gets three generated files: ``README.md``,
``SNAPSHOT.json`` (the commit) and ``MANIFEST.sha256`` (every file and its
SHA-256). ``sync`` compares each remote file's SHA-256 with the local one and
uploads only what differs, deletes remote files that git no longer tracks, and
writes the three generated files last. A run that dies half-way therefore
leaves the previous manifest in place, and ``verify`` reports the drift until
the next run repairs it. ``verify`` fails on any missing, extra or changed
file.

OSF registrations are frozen and cannot be deleted, so this script never
creates one. A registration is made by hand per release
(docs/06-reproducibility.md).

  python scripts/osf_sync.py check  [--commit REV]
  python scripts/osf_sync.py sync   [--commit REV]    needs OSF_TOKEN
  python scripts/osf_sync.py verify [--commit REV]    needs OSF_TOKEN
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
GITHUB = "https://github.com/darklordVirtual/REMORA-research"
OSF_PROJECT = "5hfae"
GENERATED = ("README.md", "SNAPSHOT.json", "MANIFEST.sha256")
LICENCE_LINE = "BUSL-1.1 (source-available, not open source)"


@dataclass(frozen=True)
class Component:
    key: str
    node: str
    title: str
    summary: str
    prefixes: tuple[str, ...]
    files: tuple[str, ...] = ()
    start: tuple[str, ...] = ()

    def owns(self, path: str) -> bool:
        return path in self.files or any(path.startswith(p) for p in self.prefixes)


LAYOUT: tuple[Component, ...] = (
    Component(
        "paper", "g3mwn", "Paper",
        "The REMORA paper (PDF, LaTeX source and Markdown rendering), its mathematical "
        "supplement, claim ledger and figure notes.",
        ("paper/",),
        start=("paper/remora_paper.pdf", "paper/remora_paper.md", "paper/claim_ledger.md"),
    ),
    Component(
        "docs", "ved2p", "Documentation and assurance registers",
        "Project documentation, the machine-readable assurance registers (claims, "
        "capabilities, documents), negative results, licensing and the AI-use disclosure.",
        ("docs/", "legal/", "LICENSES/", ".claude/"),
        ("README.md", "ARCHITECTURE.md", "DEVELOPER_OVERVIEW.md", "CONTRIBUTING.md",
         "CHANGELOG.md", "NEGATIVE_RESULTS.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
         "CLAUDE.md", "LICENSE", "NOTICE", "CITATION.cff", ".zenodo.json", "mkdocs.yml"),
        ("docs/README.md", "docs/assurance/claim_register_v1.yaml",
         "docs/assurance/capability_register_v1.yaml", "NEGATIVE_RESULTS.md", "docs/AI_USE.md"),
    ),
    Component(
        "software", "fmrnx", "Reference implementation",
        "The `remora` Python package, the execution API servers, Cloudflare workers, the "
        "evidence console frontend, integrations, deployment manifests, database migrations "
        "and JSON schemas.",
        ("remora/", "servers/", "workers/", "frontend/", "integrations/", "deploy/", "db/",
         "schemas/", "examples/"),
        ("pyproject.toml", "requirements-lock.txt", "requirements-ci.lock",
         "requirements-mutation.in", "requirements-mutation.lock",
         "requirements-release.in", "requirements-release.lock",
         "requirements-federation.in", "requirements-federation.lock",
         "requirements-federation-bootstrap.in",
         "requirements-federation-bootstrap.lock", "requirements-agentharm.in",
         "requirements-agentharm.lock", "Makefile", ".nvmrc",
         ".dockerignore", ".gitattributes", ".gitignore"),
        ("remora/", "servers/execution_api.py", "schemas/", "pyproject.toml"),
    ),
    Component(
        "verification", "wbps3", "Tests, conformance and formal models",
        "The pytest suite, conformance profiles and test vectors, formal models, the "
        "evaluation pack, and the CI workflows that run them on every commit.",
        ("tests/", "conformance/", "formal/", "vectors/", "eval_pack/", "ci/", ".github/"),
        (".gitleaks.toml", ".gitleaksignore"),
        ("tests/", "conformance/", "formal/", ".github/workflows/ci.yml"),
    ),
    Component(
        "experiments", "37jk8", "Experiments and benchmarks",
        "Experiment harnesses, benchmark runners and the scripts that produce and check "
        "the committed results.",
        ("experiments/", "benchmarks/", "scripts/"),
        start=("experiments/", "benchmarks/", "scripts/"),
    ),
    Component(
        "data", "87zmu", "Data and evidence artifacts",
        "Benchmark datasets and holdout sets, run outputs, sealed evidence artifacts and "
        "provenance records. Claims in the register resolve to files here.",
        ("artifacts/", "results/", "data/", "datasets/", "provenance/"),
        start=("artifacts/", "results/", "data/", "provenance/"),
    ),
)

# The project root carries an overview and the two files a visitor looks for first.
ROOT_COPIES = ("LICENSE", "CITATION.cff")


class LayoutError(Exception):
    pass


@dataclass
class Snapshot:
    commit: str
    commit_date: str
    files: dict[str, bytes]


@dataclass
class Plan:
    """What one OSF node should hold: relative path -> bytes, plus its wiki."""

    node: str
    title: str
    files: dict[str, bytes] = field(default_factory=dict)
    wiki: str = ""


def assign(paths: list[str]) -> dict[str, list[str]]:
    by_key: dict[str, list[str]] = {c.key: [] for c in LAYOUT}
    bad = []
    for path in paths:
        hits = [c.key for c in LAYOUT if c.owns(path)]
        if len(hits) != 1:
            bad.append(f"{path}: {', '.join(hits) or 'no component'}")
        else:
            by_key[hits[0]].append(path)
    if bad:
        raise LayoutError("files not assigned to exactly one OSF component:\n  " + "\n  ".join(bad))
    return by_key


def read_snapshot(commit: str) -> Snapshot:
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(ROOT), *args])

    full = git("rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    date = git("show", "-s", "--format=%cI", full).decode().strip()
    files = {}
    with tarfile.open(fileobj=io.BytesIO(git("archive", "--format=tar", full))) as tar:
        for member in tar.getmembers():
            if member.isfile():
                fh = tar.extractfile(member)
                assert fh is not None
                files[member.name] = fh.read()
    return Snapshot(full, date, files)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------- research documentation
#
# The OSF pages describe the research from the repository's own records rather
# than restating it: the paper's abstract, the claim register, the dataset
# manifests and the analysis plans. A result therefore appears on OSF only as
# the register states it, and changes there when the register changes.

# Where each part of the research record lives. ``check`` fails if a path is
# missing, so the map cannot point at a moved or deleted document.
RESEARCH_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Problem, contribution and results", ("paper/remora_paper.pdf", "paper/remora_paper.md")),
    ("Research questions and work packages", ("docs/13-research-frontier-roadmap.md",)),
    ("System design (the object of study)", ("ARCHITECTURE.md", "docs/01-architecture.md")),
    ("Threat model", ("docs/08-security.md", "docs/assurance/threat_model_v1.md")),
    ("Experiments and benchmark tables", ("docs/03-experiments.md",)),
    ("Analysis plans, fixed before data", ("docs/assurance/",)),
    ("Claims and the evidence each resolves to", ("docs/assurance/claim_register_v1.yaml",
                                                  "docs/evidence/claim_evidence_matrix.md")),
    ("Negative results and falsified hypotheses", ("NEGATIVE_RESULTS.md",
                                                   "docs/04-negative-results-detail.md")),
    ("Rules for stating a claim", ("docs/05-claim-hygiene.md",)),
    ("Reproducing the results", ("docs/06-reproducibility.md",)),
    ("Related work", ("docs/09-related-work.md",)),
    ("Open review objections", ("docs/review/PEER_REVIEW_FINDINGS.md",)),
    ("AI-assisted development", ("docs/AI_USE.md",)),
    ("Licensing and third-party material", ("LICENSE", "legal/THIRD_PARTY_NOTICES.md")),
)
CLAIM_REGISTER = "docs/assurance/claim_register_v1.yaml"
PAPER_MD = "paper/remora_paper.md"


def _text(snap: Snapshot, path: str) -> str | None:
    data = snap.files.get(path)
    return data.decode("utf-8") if data is not None else None


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _cell(value: Any) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _exists(snap: Snapshot, path: str) -> bool:
    return path in snap.files or any(p.startswith(path) for p in snap.files if path.endswith("/"))


def missing_research_paths(snap: Snapshot) -> list[str]:
    return [p for _, paths in RESEARCH_MAP for p in paths if not _exists(snap, p)]


def abstract(snap: Snapshot) -> str:
    """The paper's abstract paragraphs, without claim anchors or the keyword list."""
    text = _text(snap, PAPER_MD)
    if text is None or "\n## Abstract\n" not in text:
        return ""
    body = text.split("\n## Abstract\n", 1)[1].split("\n## ", 1)[0]
    body = body.split("**Keywords:**", 1)[0]
    lines = [ln for ln in body.splitlines() if not ln.strip().startswith("<!--")]
    return "\n".join(lines).strip()


def claims_table(snap: Snapshot) -> str:
    text = _text(snap, CLAIM_REGISTER)
    if text is None:
        return ""
    import yaml

    claims = yaml.safe_load(text).get("claims", [])
    order = {"active": 0, "superseded": 1}
    rows = sorted(claims, key=lambda c: (order.get(c.get("status"), 2), c["id"]))
    lines = ["| Claim | Result | Status | Evidence level | Measurement |", "|---|---|---|---|---|"]
    for c in rows:
        lines.append(f"| {c['id']} | {_cell(c.get('title', ''))} | {c.get('status', '')} | "
                     f"{c.get('evidence_level', '')} | {c.get('blindness') or 'not stated'} |")
    active = sum(1 for c in claims if c.get("status") == "active")
    return (f"{len(claims)} claims, {active} active. A superseded claim stays listed with what "
            f"replaced it. \"blind\" means evaluated once on a sealed set against targets fixed "
            f"beforehand; \"development\" means measured on data the system had seen.\n\n"
            + "\n".join(lines))


def datasets_table(snap: Snapshot) -> str:
    rows = []
    for path in sorted(p for p in snap.files if p.startswith("data/") and p.endswith("/manifest.json")
                       and p.count("/") == 2):
        try:
            m = json.loads(snap.files[path])
        except ValueError:
            continue
        name = path.split("/")[1]
        n = m.get("n_episodes", "")
        if not n and isinstance(m.get("files"), dict):
            n = sum(f.get("n_episodes", 0) for f in m["files"].values() if isinstance(f, dict)) or ""
        plan = m.get("sap_ref") or m.get("plan") or m.get("sap") or ""
        up = m.get("upstream") if isinstance(m.get("upstream"), dict) else {}
        source = f"{up['repo'].rsplit('/', 1)[-1]} ({up.get('license', '')})" if up.get("repo") else ""
        if not source and isinstance(m.get("sources"), dict):
            source = ", ".join(f"{k} ({v.get('license', '')})" for k, v in m["sources"].items()
                               if isinstance(v, dict) and v.get("redistributable", True))
        rows.append(f"| `data/{name}/` | {_cell(m.get('status', ''))} | {n} | {_cell(source)} | "
                    f"{_cell(plan)} |")
    packs = []
    for path in sorted(p for p in snap.files if p.startswith("datasets/") and p.endswith("/README.md")
                       and p.count("/") == 2):
        packs.append(f"| `{path.rsplit('/', 1)[0]}/` | {_cell(_first_heading(_text(snap, path) or ''))} |")
    out = []
    if rows:
        out += ["Benchmark tracks. `evaluated` means the sealed set has been run once and is spent; "
                "a spent set is never reused as a blind set.", "",
                "| Track | Status | Episodes | Upstream source (licence) | Plan |", "|---|---|---|---|---|",
                *rows, ""]
    if packs:
        out += ["Evidence packs.", "", "| Pack | Title |", "|---|---|", *packs, ""]
    return "\n".join(out).strip()


def plans_table(snap: Snapshot) -> str:
    paths = sorted(p for p in snap.files if p.startswith("docs/assurance/")
                   and (p.rsplit("/", 1)[-1].startswith("statistical_analysis_plan")
                        or p.rsplit("/", 1)[-1].startswith("ws1_composition_study_v"))
                   and p.endswith(".md"))
    if not paths:
        return ""
    rows = [f"| `{p}` | {_cell(_first_heading(_text(snap, p) or ''))} |" for p in paths]
    return ("Each plan fixed its hypotheses, targets and analysis before the data it governs were "
            "generated or unsealed. Its heading states whether it is in force, executed, superseded "
            "or a draft.\n\n| Plan | Title |\n|---|---|\n" + "\n".join(rows))


def verification_summary(snap: Snapshot) -> str:
    tests = sum(1 for p in snap.files if p.startswith("tests/") and p.rsplit("/", 1)[-1].startswith("test_")
                and p.endswith(".py"))
    flows = sorted(p.rsplit("/", 1)[-1] for p in snap.files if p.startswith(".github/workflows/"))
    if not tests and not flows:
        return ""
    return (f"{tests} pytest modules under `tests/`. CI workflows in `.github/workflows/`: "
            + ", ".join(f"`{f}`" for f in flows) + ". A passing internal test is not external "
            "verification; which properties are established, and how, is in the capability "
            "register in the Documentation component.")


def _section(title: str, body: str) -> str:
    return f"\n## {title}\n\n{body}\n" if body else ""


def component_extra(key: str, snap: Snapshot) -> str:
    if key == "paper":
        return _section("Abstract", abstract(snap))
    if key == "data":
        return (_section("Datasets", datasets_table(snap))
                + _section("Sources and rights", SOURCES_NOTE))
    if key == "experiments":
        return _section("Analysis plans", plans_table(snap) + (
            "\n\nThe plans are stored in the Documentation component." if plans_table(snap) else ""))
    if key == "verification":
        return _section("What is tested", verification_summary(snap))
    if key == "docs":
        return _section("Assurance registers", registers_list(snap))
    return ""


def registers_list(snap: Snapshot) -> str:
    regs = sorted(p for p in snap.files if p.startswith("docs/assurance/") and p.count("/") == 2
                  and p.endswith((".yaml", ".yml")))
    if not regs:
        return ""
    return ("The machine-readable registers. When a document disagrees with one of them, the "
            "register wins. The claims are summarised on the project page.\n\n"
            + "\n".join(f"- `{p}`" for p in regs))


SOURCES_NOTE = (
    "Data here is either sampled from the upstream benchmarks named in the table, under their own "
    "licences, or generated in this repository. Third-party material is not relicensed; "
    "`legal/THIRD_PARTY_NOTICES.md` (Documentation component) lists every source and its terms. "
    "Sources that may not be redistributed (ToolSandbox) are built locally and never committed. "
    "Stored model outputs are subject to the providers' terms.")


def _component_readme(c: Component, snap: Snapshot, paths: list[str], size: int) -> str:
    tree = f"{GITHUB}/tree/{snap.commit}"
    start = "\n".join(f"- [`{s}`]({tree}/{s.rstrip('/')})" for s in c.start)
    tops = sorted({p.split("/")[0] + ("/" if "/" in p else "") for p in paths})
    return f"""# REMORA: {c.title}

{c.summary}
{component_extra(c.key, snap)}
This component mirrors the repository at commit
[`{snap.commit[:8]}`]({GITHUB}/commit/{snap.commit}) ({snap.commit_date[:10]}). Paths match
the repository, so a file here at `x/y.py` is `x/y.py` in git. The mirror is
updated from CI on every push to master; registrations of this project are
frozen copies of one commit.

## Start here

{start}

## Contents

{len(paths)} files, {size / 1e6:.1f} MB, under: {", ".join(f"`{t}`" for t in tops)}

## Checking the snapshot

`MANIFEST.sha256` lists the SHA-256 of every file in this component.
After downloading the component, run `sha256sum -c MANIFEST.sha256` from its root.
To compare against git, check out `{snap.commit}` and run the same command there.

## Licence

Business Source License 1.1. The code is source-available, not open source.
See `LICENSE` and `legal/` in the Documentation component.
"""


def _research_map(snap: Snapshot, rows: list[tuple[Component, int]]) -> str:
    def where(path: str) -> str:
        key = next((c.key for c, _ in rows if c.owns(path) or
                    any(f.startswith(path) and c.owns(f) for f in snap.files if path.endswith("/"))),
                   None)
        comp = next((c for c, _ in rows if c.key == key), None)
        return f"[`{path}`](https://osf.io/{comp.node}/)" if comp else f"`{path}`"

    lines = ["| Part of the record | Where |", "|---|---|"]
    for label, paths in RESEARCH_MAP:
        present = [p for p in paths if _exists(snap, p)]
        if present:
            lines.append(f"| {label} | {', '.join(where(p) for p in present)} |")
    return "\n".join(lines)


def _root_readme(snap: Snapshot, rows: list[tuple[Component, int]]) -> str:
    table = "\n".join(
        f"| [{c.title}](https://osf.io/{c.node}/) | {c.summary} | {n:,} |" for c, n in rows)
    total = sum(n for _, n in rows)
    summary = abstract(snap)
    return f"""# REMORA: Verifiable Authority for Autonomous AI Agents

An AI agent can propose any tool call. REMORA decides whether that exact call
may run (ACCEPT, VERIFY, ABSTAIN or ESCALATE), enforces the decision at the
point of execution, and keeps the evidence.
{_section("Abstract", summary + chr(10) * 2 + "From the paper; each result cites its entry in the claim register." if summary else "")}
## The research record

{_research_map(snap, rows)}

When documents disagree, the machine-readable registers under
`docs/assurance/` win. A module in the Reference implementation is not
necessarily on the enforcing path; the capability register says what is wired.
{_section("Claims", claims_table(snap))}
## This project

This OSF project mirrors the REMORA-research repository at commit
[`{snap.commit[:8]}`]({GITHUB}/commit/{snap.commit}) ({snap.commit_date[:10]}), split
into six components. CI updates the mirror on every push to master and checks
it against the commit's manifest weekly. The GitHub storage on this page shows
the live repository.

**Status:** research and shadow-mode software with no production certification.
External replication is pending.

## Components

| Component | What it holds | Files |
|---|---|---|
{table}

Each component has its own README, a `SNAPSHOT.json` naming the commit, and a
`MANIFEST.sha256` covering every file. Paths inside a component match the
repository, so the six components together reproduce the tree at that commit
({total:,} files).

## Registrations

Registrations of this project are Open-Ended Registrations of a completed
snapshot, one per release. They are not preregistrations: the analyses in them
were run before they were registered. The repository's own pre-registration
record is the set of analysis plans under `docs/assurance/`, listed in the
Experiments component.

## Rights, data and corrections

{RIGHTS_NOTE}

## Licence and citation

Business Source License 1.1. The code is source-available, not open source;
see `LICENSE` and `legal/` in the Documentation component. Cite with
`CITATION.cff`.

Research lead: Stian Skogbrott, independent researcher. The work has no
external funding.
"""


# Stated on the project page because OSF's terms make the depositor answer for
# rights, licence restrictions and the accuracy of deposited data.
RIGHTS_NOTE = """\
- **Rights.** The original material is the author's and is licensed under
  BUSL-1.1. Third-party datasets, schemas and fixtures stay under their own
  licences and are listed with their terms in `legal/THIRD_PARTY_NOTICES.md`.
  Material that may not be redistributed is not in the repository.
- **Human participants.** No dataset here was collected from human
  participants. The data are sampled from public benchmarks, generated in the
  repository, or are outputs of the models named in the result artifacts.
- **Corrections.** Errors are corrected in git, and this mirror follows within
  one CI run. A result that is revised is not removed: the claim register marks
  it superseded and names its replacement, and `NEGATIVE_RESULTS.md` keeps
  what did not hold. Registrations stay as they were registered.
- **Copies.** The GitHub repository is the primary copy and this project a
  verified mirror of it; neither is the only copy."""


def build_plans(snap: Snapshot, strict: bool = False) -> list[Plan]:
    by_key = assign(sorted(snap.files))
    if strict and (gone := missing_research_paths(snap)):
        raise LayoutError("RESEARCH_MAP names paths that are not tracked:\n  " + "\n  ".join(gone))
    plans, rows = [], []
    for c in LAYOUT:
        paths = by_key[c.key]
        size = sum(len(snap.files[p]) for p in paths)
        files = {p: snap.files[p] for p in paths}
        manifest = "".join(f"{sha256(snap.files[p])}  {p}\n" for p in paths)
        meta = {"component": c.title, "repository": GITHUB, "commit": snap.commit,
                "commit_date": snap.commit_date, "files": len(paths), "bytes": size,
                "manifest": "MANIFEST.sha256", "license": LICENCE_LINE}
        readme = _component_readme(c, snap, paths, size)
        files["MANIFEST.sha256"] = manifest.encode()
        files["SNAPSHOT.json"] = (json.dumps(meta, indent=2) + "\n").encode()
        files["README.md"] = readme.encode()
        plans.append(Plan(c.node, c.title, files, readme))
        rows.append((c, len(paths)))
    root_readme = _root_readme(snap, rows)
    root_files = {name: snap.files[name] for name in ROOT_COPIES}
    root_files["README.md"] = root_readme.encode()
    plans.insert(0, Plan(OSF_PROJECT, "REMORA", root_files, root_readme))
    return plans


# --------------------------------------------------------------------- remote


@dataclass
class RemoteTree:
    files: dict[str, tuple[str, str]]   # rel path -> (sha256, osf path)
    folders: dict[str, str]             # rel folder ("" is the root) -> osf path


class Storage(Protocol):
    def tree(self, node: str) -> RemoteTree: ...
    def mkdir(self, node: str, parent: str, name: str) -> str: ...
    def create(self, node: str, parent: str, name: str, data: bytes) -> None: ...
    def update(self, node: str, path: str, data: bytes) -> None: ...
    def delete(self, node: str, path: str) -> None: ...
    def wiki(self, node: str) -> str | None: ...
    def set_wiki(self, node: str, text: str) -> None: ...


class OSF:
    """The OSF v2 API and its WaterButler file service, behind ``Storage``."""

    api = "https://api.osf.io/v2"
    files_api = "https://files.osf.io/v1/resources"

    def __init__(self, token: str) -> None:
        import requests

        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _call(self, method: str, url: str, ok: tuple[int, ...] = (200, 201, 204),
              **kw: Any) -> Any:
        # OSF throttles bursts with 429; honour Retry-After and back off to two
        # minutes rather than failing a run that is merely being paced.
        for attempt in range(12):
            response = self.session.request(method, url, timeout=300, **kw)
            if response.status_code in (429, 500, 502, 503, 504):
                retry_after = response.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else 2 ** attempt
                time.sleep(min(max(wait, 1), 120))
                continue
            if response.status_code not in ok:
                raise RuntimeError(f"{method} {url} -> {response.status_code}: "
                                   f"{response.text[:300]}")
            return response
        raise RuntimeError(f"{method} {url}: gave up after retries")

    def _list(self, node: str, path: str) -> list[dict[str, Any]]:
        url: str | None = f"{self.api}/nodes/{node}/files/osfstorage{path}?page[size]=100"
        items: list[dict[str, Any]] = []
        while url:
            body = self._call("GET", url).json()
            items += body["data"]
            url = body["links"].get("next")
        return items

    def tree(self, node: str) -> RemoteTree:
        out = RemoteTree({}, {"": "/"})
        queue = [("", "/")]
        while queue:
            rel, path = queue.pop()
            for item in self._list(node, path):
                a = item["attributes"]
                child = f"{rel}/{a['name']}" if rel else a["name"]
                if a["kind"] == "folder":
                    out.folders[child] = a["path"]
                    queue.append((child, a["path"]))
                else:
                    out.files[child] = (a["extra"]["hashes"].get("sha256") or "", a["path"])
        return out

    def _wb(self, node: str, path: str) -> str:
        return f"{self.files_api}/{node}/providers/osfstorage{path}"

    # A create retried after a lost response (429, 5xx) meets its own first
    # attempt and gets 409, so the retry carries on with the existing item
    # instead of failing the run. A file conflict names the item in its body;
    # a folder conflict does not (``"data": {}``), so it is looked up.
    def _lookup(self, node: str, parent: str, name: str) -> str:
        for item in self._list(node, parent):
            if item["attributes"]["name"] == name:
                return str(item["attributes"]["path"])
        raise RuntimeError(f"409 for {name!r} in {parent} but no such item is listed")

    def mkdir(self, node: str, parent: str, name: str) -> str:
        r = self._call("PUT", f"{self._wb(node, parent)}?kind=folder&name={quote(name)}",
                       ok=(201, 409))
        if r.status_code == 409:
            return self._lookup(node, parent, name)
        return str(r.json()["data"]["attributes"]["path"])

    def create(self, node: str, parent: str, name: str, data: bytes) -> None:
        r = self._call("PUT", f"{self._wb(node, parent)}?kind=file&name={quote(name)}",
                       ok=(201, 409), data=data)
        if r.status_code == 409:
            ident = str((r.json().get("data") or {}).get("id", ""))
            path = "/" + ident.split("/", 1)[1] if "/" in ident else self._lookup(node, parent, name)
            self.update(node, path, data)

    def update(self, node: str, path: str, data: bytes) -> None:
        self._call("PUT", f"{self._wb(node, path)}?kind=file", data=data)

    def delete(self, node: str, path: str) -> None:
        self._call("DELETE", self._wb(node, path))

    def _home(self, node: str) -> dict[str, Any] | None:
        wikis = self._call("GET", f"{self.api}/nodes/{node}/wikis/").json()["data"]
        return next((w for w in wikis if w["attributes"]["name"].lower() == "home"), None)

    def wiki(self, node: str) -> str | None:
        home = self._home(node)
        if home is None:
            return None
        return str(self._call("GET", f"{self.api}/wikis/{home['id']}/content/").text)

    def set_wiki(self, node: str, text: str) -> None:
        jsonapi = {"Content-Type": "application/vnd.api+json"}
        home = self._home(node)
        if home is None:
            body = {"data": {"type": "wikis", "attributes": {"name": "home", "content": text}}}
            self._call("POST", f"{self.api}/nodes/{node}/wikis/", json=body, headers=jsonapi)
        else:
            body = {"data": {"type": "wiki-versions", "attributes": {"content": text}}}
            self._call("POST", f"{self.api}/wikis/{home['id']}/versions/", json=body,
                       headers=jsonapi)


@dataclass
class Drift:
    missing: list[str]
    changed: list[str]
    extra: list[str]

    def __bool__(self) -> bool:
        return bool(self.missing or self.changed or self.extra)


def compare(plan: Plan, remote: RemoteTree) -> Drift:
    want = {rel: sha256(data) for rel, data in plan.files.items()}
    return Drift(
        missing=sorted(r for r in want if r not in remote.files),
        changed=sorted(r for r in want if r in remote.files and remote.files[r][0] != want[r]),
        extra=sorted(r for r in remote.files if r not in want),
    )


def _ensure_folder(store: Storage, node: str, remote: RemoteTree, rel: str) -> str:
    if rel not in remote.folders:
        parent, _, name = rel.rpartition("/")
        remote.folders[rel] = store.mkdir(node, _ensure_folder(store, node, remote, parent), name)
    return remote.folders[rel]


def sync_plan(store: Storage, plan: Plan, workers: int = 4) -> Drift:
    """Bring one node in line with its plan. Generated files are written last."""
    remote = store.tree(plan.node)
    drift = compare(plan, remote)
    todo = drift.missing + drift.changed
    for rel in todo:  # folders first and in order, so parallel uploads never race on mkdir
        if "/" in rel:
            _ensure_folder(store, plan.node, remote, rel.rpartition("/")[0])

    def put(rel: str) -> None:
        if rel in remote.files:
            store.update(plan.node, remote.files[rel][1], plan.files[rel])
        else:
            parent, _, name = rel.rpartition("/")
            store.create(plan.node, remote.folders[parent], name, plan.files[rel])

    content = [r for r in todo if r not in GENERATED]
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(put, content))
    for rel in drift.extra:
        store.delete(plan.node, remote.files[rel][1])
    for rel in [r for r in todo if r in GENERATED]:
        put(rel)
    _prune_empty(store, plan, remote)
    if store.wiki(plan.node) != plan.wiki:
        store.set_wiki(plan.node, plan.wiki)
    return drift


def _prune_empty(store: Storage, plan: Plan, remote: RemoteTree) -> None:
    wanted = {rel.rpartition("/")[0] for rel in plan.files}
    for rel in list(wanted):
        while "/" in rel:
            rel = rel.rpartition("/")[0]
            wanted.add(rel)
    for rel in sorted(remote.folders, key=len, reverse=True):
        if rel and rel not in wanted:
            store.delete(plan.node, remote.folders.pop(rel))


def verify_plans(store: Storage, plans: list[Plan]) -> list[str]:
    problems = []
    for plan in plans:
        drift = compare(plan, store.tree(plan.node))
        for kind in ("missing", "changed", "extra"):
            problems += [f"{plan.node} ({plan.title}): {kind} {rel}" for rel in getattr(drift, kind)]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("check", "sync", "verify"))
    parser.add_argument("--commit", default="HEAD")
    args = parser.parse_args(argv)
    try:
        snap = read_snapshot(args.commit)
        plans = build_plans(snap, strict=True)
    except LayoutError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    total = sum(len(p.files) for p in plans)
    if args.mode == "check":
        print(f"OK: {len(snap.files)} tracked files at {snap.commit[:12]} map onto "
              f"{len(plans)} OSF nodes ({total} files with generated ones)")
        return 0
    token = os.environ.get("OSF_TOKEN", "")
    if not token:
        print("FAIL: OSF_TOKEN is not set", file=sys.stderr)
        return 2
    store = OSF(token)
    if args.mode == "sync":
        for plan in plans:
            d = sync_plan(store, plan)
            print(f"{plan.node} {plan.title}: {len(d.missing)} new, {len(d.changed)} changed, "
                  f"{len(d.extra)} removed")
    problems = verify_plans(store, plans)
    for line in problems:
        print(f"DRIFT {line}", file=sys.stderr)
    if problems:
        print(f"FAIL: OSF differs from {snap.commit[:12]} in {len(problems)} places",
              file=sys.stderr)
        return 1
    print(f"OK: OSF matches {snap.commit[:12]} exactly ({total} files on {len(plans)} nodes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
