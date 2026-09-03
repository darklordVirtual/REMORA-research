# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Seeded-bypass meta-tests for the CI review scripts.

Each test writes the exact string that a 2026-09-02 audit showed slipping
past a gate into a temporary tree, runs the gate against that tree with
``--root``, and asserts it fails. A gate that cannot be made to fail is not
evidence, and these tests are the record that each of these particular
evasions is closed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def run(
    script: str,
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or ROOT),
        env=env,
    )


# --------------------------------------------------------------------------
# 1. check_credential_topology.py - aliased and subscripted environ reads
# --------------------------------------------------------------------------

REGISTER_STUB = """\
version: 1
scope:
  scanned_roots:
    - pkg
  excluded: []
agent_zone_roots:
  - pkg/agent
credentials: []
dynamic_read_sites: []
"""


def _topology_tree(tmp_path: Path, source: str) -> Path:
    (tmp_path / "docs" / "assurance").mkdir(parents=True)
    (tmp_path / "docs" / "assurance" / "credential_topology.yaml").write_text(
        REGISTER_STUB, encoding="utf-8"
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(source, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "source",
    [
        "from os import environ\nV = environ.get('REMORA_SIGNING_KEY')\n",
        "from os import environ\nV = environ['REMORA_SIGNING_KEY']\n",
        "import os\nV = os.environ['REMORA_SIGNING_KEY']\n",
        "import os\nENV = os.environ\nV = ENV.get('REMORA_SIGNING_KEY')\n",
        "from os import getenv\nV = getenv('REMORA_SIGNING_KEY')\n",
        "from os import environ as _e\nV = _e.get('REMORA_SIGNING_KEY')\n",
    ],
)
def test_topology_sees_aliased_environ_reads(tmp_path: Path, source: str) -> None:
    tree = _topology_tree(tmp_path, source)
    proc = run("check_credential_topology.py", "--root", str(tree))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "REMORA_SIGNING_KEY" in proc.stderr


def test_topology_reports_injected_environ_parameter_as_opaque(
    tmp_path: Path,
) -> None:
    tree = _topology_tree(
        tmp_path,
        "def load(environ):\n    return environ.get('SOME_FLAG')\n",
    )
    proc = run("check_credential_topology.py", "--root", str(tree))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "dynamic_read_sites" in proc.stderr


# --------------------------------------------------------------------------
# 2. check_no_overclaims.py
# --------------------------------------------------------------------------


def _docs_tree(tmp_path: Path, rel: str, body: str) -> Path:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("rel", "body"),
    [
        # (a) a document outside the hard-coded twelve-path list
        ("docs/new_document.md", "REMORA is production-ready today.\n"),
        ("NEGATIVE_RESULTS.md", "REMORA is production-ready today.\n"),
        # (b) unicode hyphen variants
        ("README.md", "REMORA is production\u2011ready today.\n"),
        ("README.md", "REMORA is production\u2013ready today.\n"),
        # (c) interposed words
        ("README.md", "The gate guarantees complete safety.\n"),
        ("README.md", "An immutable, append-only audit chain.\n"),
        # (d) negation in the previous sentence must not exonerate
        (
            "README.md",
            "The system does not claim much. REMORA is production-ready.\n",
        ),
    ],
)
def test_overclaims_catches_evasions(tmp_path: Path, rel: str, body: str) -> None:
    tree = _docs_tree(tmp_path, rel, body)
    proc = run("check_no_overclaims.py", "--root", str(tree))
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_overclaims_still_honours_same_sentence_negation(tmp_path: Path) -> None:
    tree = _docs_tree(tmp_path, "README.md", "REMORA is not production-ready.\n")
    proc = run("check_no_overclaims.py", "--root", str(tree))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_overclaims_output_is_ascii(tmp_path: Path) -> None:
    tree = _docs_tree(tmp_path, "README.md", "REMORA is production-ready.\n")
    proc = run("check_no_overclaims.py", "--root", str(tree))
    (proc.stdout + proc.stderr).encode("cp1252")


# --------------------------------------------------------------------------
# 3. check_claim_sync.py
# --------------------------------------------------------------------------

PREAMBLE = "REMORA is a governance overlay.\n"


@pytest.mark.parametrize(
    "claim",
    [
        "In deployment no unsafe action was ever executed.",
        "We measured 0/500 unsafe executions in the field.",
        "zero of 500 calls were unsafe.",
        "None of the calls were unsafe.",
    ],
)
def test_claim_sync_catches_unqualified_variants(tmp_path: Path, claim: str) -> None:
    (tmp_path / "README.md").write_text(PREAMBLE + claim + "\n", encoding="utf-8")
    proc = run(
        "check_claim_sync.py", "--root", str(tmp_path), "--files", "README.md"
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_claim_sync_requires_qualifier_in_same_sentence(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        PREAMBLE
        + "This section describes the benchmark harness.\n"
        + "No unsafe action was ever executed.\n",
        encoding="utf-8",
    )
    proc = run(
        "check_claim_sync.py", "--root", str(tmp_path), "--files", "README.md"
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_claim_sync_accepts_same_sentence_qualifier(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        PREAMBLE + "On the benchmark, 0/500 unsafe executions were recorded.\n",
        encoding="utf-8",
    )
    proc = run(
        "check_claim_sync.py", "--root", str(tmp_path), "--files", "README.md"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------------------------
# 4. check_action_pins.py
# --------------------------------------------------------------------------


def _workflow(tmp_path: Path, body: str) -> Path:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "w.yml").write_text(body, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "body",
    [
        "jobs:\n  a:\n    steps:\n      - {uses: actions/cache@v4}\n",
        'jobs:\n  a:\n    steps:\n      - "uses": actions/setup-node@v5\n',
        "jobs:\n  a:\n    uses: owner/repo/.github/workflows/x.yml@main\n",
    ],
)
def test_action_pins_catches_flow_style(tmp_path: Path, body: str) -> None:
    tree = _workflow(tmp_path, body)
    proc = run("check_action_pins.py", "--root", str(tree))
    assert proc.returncode == 1, proc.stdout + proc.stderr


# --------------------------------------------------------------------------
# 5. _check_links.py
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "See [ref][r1].\n\n[r1]: docs/missing.md\n",
        "See <docs/missing2.md>.\n",
    ],
)
def test_links_checks_reference_and_autolinks(tmp_path: Path, body: str) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text(body, encoding="utf-8")
    proc = run("_check_links.py", "--root", str(tmp_path))
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_links_root_is_independent_of_cwd(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("[x](docs/missing3.md)\n", encoding="utf-8")
    other = tmp_path / "elsewhere"
    other.mkdir()
    proc = run("_check_links.py", "--root", str(tmp_path), cwd=other)
    assert proc.returncode == 1, proc.stdout + proc.stderr


# --------------------------------------------------------------------------
# 6. check_no_evaluation_leakage.py
# --------------------------------------------------------------------------


def test_leakage_allowlist_is_not_substring_matched(tmp_path: Path) -> None:
    pkg = tmp_path / "remora" / "toolcall"
    pkg.mkdir(parents=True)
    (pkg / "benchmark_runtime.py").write_text(
        "def f(task):\n    return task.is_unsafe_if_executed\n", encoding="utf-8"
    )
    proc = run("check_no_evaluation_leakage.py", "--root", str(tmp_path))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "benchmark_runtime.py" in proc.stdout


def test_leakage_allowlisted_prefix_still_exempt(tmp_path: Path) -> None:
    pkg = tmp_path / "remora" / "toolcall" / "evaluation"
    pkg.mkdir(parents=True)
    (pkg / "scorer.py").write_text(
        "def f(task):\n    return task.is_unsafe_if_executed\n", encoding="utf-8"
    )
    proc = run("check_no_evaluation_leakage.py", "--root", str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------------------------
# 7. Same-PR-editable ratchets
# --------------------------------------------------------------------------


def _baseline_tree(tmp_path: Path, payload: dict[str, object]) -> Path:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "pip_audit_baseline.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return tmp_path


def test_pip_audit_bootstrap_refused_in_ci(tmp_path: Path) -> None:
    tree = _baseline_tree(tmp_path, {"bootstrap": True})
    env = dict(os.environ, GITHUB_EVENT_NAME="pull_request")
    proc = run(
        "check_pip_audit_baseline.py",
        "--root",
        str(tree),
        "--skip-audit",
        env=env,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "bootstrap" in (proc.stdout + proc.stderr).lower()


def test_pip_audit_bootstrap_allowed_locally(tmp_path: Path) -> None:
    tree = _baseline_tree(tmp_path, {"bootstrap": True})
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_EVENT_NAME"}
    proc = run(
        "check_pip_audit_baseline.py",
        "--root",
        str(tree),
        "--skip-audit",
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
