# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A capability's status is a claim about code, so it must age with the code.

The register used to carry audit dates with nothing to compare them against: a
core change could move every implementation cited as evidence and no gate would
notice that the caveats now described code that no longer existed. These tests
exercise the binding both ways — a real repository where the file moves after
the recorded revision must go STALE, and the committed register must be clean
and honestly counted.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_capability_freshness.py"


def _load():
    spec = importlib.util.spec_from_file_location("cap_freshness", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _load()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository with one implementation file and one commit."""
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    source = tmp_path / "remora" / "enforcement"
    source.mkdir(parents=True)
    (source / "gate.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "first")
    return tmp_path


def _sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _touch(repo: Path) -> None:
    (repo / "remora" / "enforcement" / "gate.py").write_text("x = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "change the implementation"],
        cwd=repo, check=True, capture_output=True,
    )


CAP = {"id": "CAP-TEST", "evidence": ["remora/enforcement/gate.py", "tests/test_x.py"]}


def test_unchanged_evidence_is_bound(gate, repo) -> None:
    status, _ = gate.classify({**CAP, "verified_at_sha": _sha(repo)}, cwd=repo)
    assert status == "BOUND"


def test_evidence_moving_after_the_verified_sha_is_stale(gate, repo) -> None:
    """The whole point: an audit does not survive the code it audited."""
    sha = _sha(repo)
    _touch(repo)
    status, detail = gate.classify({**CAP, "verified_at_sha": sha}, cwd=repo)
    assert status == "STALE"
    # Names the file whose content moved, not a commit count: a count cannot
    # tell a squash from a change, which is why it was replaced (#380).
    assert "content changed" in detail
    assert "remora/enforcement/gate.py" in detail


def _commit(repo: Path, msg: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", msg], cwd=repo, check=True, capture_output=True)


def test_a_squash_that_changes_no_content_stays_bound(gate, repo) -> None:
    """The failure mode #380 names: master red after every squash-merge.

    A commit that touches the evidence path but leaves its bytes identical --
    a squash, a rebase, a cherry-pick -- is not a change to the code the
    audit was performed on. Counting it as one made the gate fire on every
    merge and trained a mechanical rebind that recorded no audit.
    """
    sha = _sha(repo)
    gate_py = repo / "remora" / "enforcement" / "gate.py"
    original = gate_py.read_text(encoding="utf-8")
    gate_py.write_text("x = 2" + chr(10), encoding="utf-8")
    _commit(repo, "change")
    gate_py.write_text(original, encoding="utf-8")
    _commit(repo, "and put it back -- the path moved, the bytes did not")

    status, detail = gate.classify({**CAP, "verified_at_sha": sha}, cwd=repo)
    assert status == "BOUND"
    # The sha is behind HEAD and the reader is told why that is fine.
    assert "content-identical" in detail
    assert "2 commit(s)" in detail


def test_a_real_change_is_still_stale_and_names_the_file(gate, repo) -> None:
    """Both directions: the content check must not weaken the gate."""
    sha = _sha(repo)
    _touch(repo)
    status, detail = gate.classify({**CAP, "verified_at_sha": sha}, cwd=repo)
    assert status == "STALE"
    assert "remora/enforcement/gate.py" in detail


def test_a_test_only_change_does_not_age_the_capability(gate, repo) -> None:
    """A caveat describes the implementation, not the test that covers it."""
    sha = _sha(repo)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("# added later\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "test only"], cwd=repo, check=True, capture_output=True
    )
    status, _ = gate.classify({**CAP, "verified_at_sha": sha}, cwd=repo)
    assert status == "BOUND"


def test_missing_sha_is_unbound_not_stale(gate, repo) -> None:
    """A capability nobody has audited yet is a backlog item, not a failure."""
    status, _ = gate.classify(dict(CAP), cwd=repo)
    assert status == "UNBOUND"


def test_an_unresolvable_sha_is_reported_not_ignored(gate, repo) -> None:
    """A shallow clone must not silently turn the gate off."""
    status, _ = gate.classify({**CAP, "verified_at_sha": "0" * 40}, cwd=repo)
    assert status == "UNKNOWN"


def test_source_evidence_excludes_tests_and_docs(gate) -> None:
    sources = gate.source_evidence(
        {"evidence": [
            "remora/enforcement/lease.py",
            "servers/execution_api.py",
            "tests/test_execution_lease.py",
            "docs/assurance/red_team_plan_v1.md",
            "scripts/opa_conformance.py",
        ]}
    )
    assert sources == ["remora/enforcement/lease.py", "servers/execution_api.py"]


# ── The committed register ───────────────────────────────────────────────────

def test_the_committed_register_has_no_stale_capability(gate) -> None:
    stale = [
        cap["id"]
        for cap in gate.load_register()["capabilities"]
        if gate.classify(cap)[0] == "STALE"
    ]
    assert not stale, f"re-audit and rebind: {stale}"


def test_the_unbound_baseline_is_not_inflated(gate) -> None:
    """The ratchet only works if the baseline is the truth, not a cushion."""
    register = gate.load_register()
    unbound = sum(
        1 for cap in register["capabilities"] if gate.classify(cap)[0] == "UNBOUND"
    )
    baseline = register["verification_binding"]["unbound_baseline"]
    assert baseline == unbound, (
        f"baseline {baseline} but {unbound} unbound — lower the baseline when a "
        f"capability is bound; it may never be raised"
    )


def test_a_bound_capability_records_who_verified_it(gate) -> None:
    for cap in gate.load_register()["capabilities"]:
        if cap.get("verified_at_sha"):
            assert cap.get("verified_by", "").strip(), (
                f"{cap['id']}: a sha without an audit record is a bare assertion"
            )


def test_ci_runs_the_gate_in_strict_mode_with_full_history() -> None:
    """A corrupt verified_at_sha must not read as a clean binding.

    An unresolvable SHA classifies as UNKNOWN, which prints a warning to
    stderr and, without --strict, does not fail. A binding to a commit that
    does not exist therefore reported success -- found by accidentally writing
    one (NEGATIVE_RESULTS section 46).

    --strict is only sound with full history: on a shallow clone every SHA
    older than the tip is equally unresolvable, so strict mode would fail on
    correct bindings. The two settings are asserted together because either
    alone is wrong.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8")

    marker = "python scripts/check_capability_freshness.py"
    assert marker in workflow, "the freshness gate is not run in CI"
    invocation = workflow[workflow.index(marker):].splitlines()[0]
    assert "--strict" in invocation, (
        "CI must run the freshness gate with --strict, or an unresolvable "
        "verified_at_sha passes as clean")

    # The job that runs it must check out full history.
    job_start = workflow.index(
        "Documentation governance (registers, profiles, README budget)")
    job = workflow[job_start:workflow.index(marker)]
    assert "fetch-depth: 0" in job, (
        "--strict needs full history; on a shallow clone it would fail on "
        "correct bindings")
