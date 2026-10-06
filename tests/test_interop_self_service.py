# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Runner measurements are distinct from runtime claim results (AGV E030)."""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import tarfile

import pytest

from scripts import interop_self_service as runner


@pytest.fixture(scope="module")
def pinned(interop_pinned_repo):
    return interop_pinned_repo


def _arguments(root, revision, output):
    return [sys.executable, str(root / runner.SCRIPT), "--revision", revision,
            "--operator", "test operator (self-declared)", "--host", "test host (self-declared)",
            "--output", str(output)]


def test_real_runtime_fresh_working_directory_and_isolated_environment(pinned, tmp_path, monkeypatch):
    root, revision = pinned
    output = tmp_path / "observation.json"
    original = subprocess.run
    observed = {}

    def capture(command, **kwargs):
        if "-I" in command:
            cwd = kwargs["cwd"]
            observed["fresh_working_directory"] = list(cwd.iterdir()) == [cwd / "source"]
            assert kwargs["env"] == runner._environment(cwd)
            assert "DEPLOYMENT_SECRET" not in kwargs["env"]
            assert "REMORA_PDP_REVOKED_KIDS" not in kwargs["env"]
        return original(command, **kwargs)

    monkeypatch.setenv("DEPLOYMENT_SECRET", "must-not-be-inherited")
    monkeypatch.setenv("REMORA_PDP_REVOKED_KIDS", "fixture-key")
    monkeypatch.setattr(runner.subprocess, "run", capture)
    assert runner.run(root, revision, list(runner.CONTRACTS), output, "test operator", 120, "test host") == 3
    assert observed["fresh_working_directory"] is True
    report = json.loads(output.read_text())
    assert report["runtime_revision"] == revision
    assert report["independence"] == "NOT_CLASSIFIED"
    assert report["authority"] == "NONE"
    assert report["execution_status"] == "COMPLETED"
    assert report["host_isolation"] == "NOT_ESTABLISHED"
    assert report["host_declaration"] == "test host"
    assert {p["contract_id"] for p in report["contracts"]} == set(runner.CONTRACTS)
    for module in ("remora/enforcement/lease.py", "remora/enforcement/gate.py",
                   "remora/governance/effect_verification.py"):
        assert report["runtime_modules"][module] == report["source_files"][module]
    assert any(c["claim_status"] == "NOT_ESTABLISHED" for p in report["contracts"] for c in p["cases"])
    assert not any(c["claim_status"] == "CONTRADICTED" for p in report["contracts"] for c in p["cases"])


@pytest.mark.parametrize("contracts, exit_code", [
    ([], 3), (["--contract", "effect-evidence-v1"], 0),
])
def test_real_cli_separates_completion_from_unestablished_claims(pinned, tmp_path, contracts, exit_code):
    root, revision = pinned
    output = tmp_path / "report.json"
    result = subprocess.run([*_arguments(root, revision, output), *contracts], capture_output=True, text=True)
    assert result.returncode == exit_code
    assert output.is_file()
    assert json.loads(output.read_text())["execution_status"] == "COMPLETED"
    assert "PASS" not in result.stdout


@pytest.mark.parametrize("failure", ["nonzero", "dependency", "killed", "timeout", "malformed", "schema"])
def test_failure_dimensions_separately(pinned, tmp_path, monkeypatch, capsys, failure):
    root, revision = pinned
    output = tmp_path / "report.json"
    original = subprocess.run

    def force_failure(command, **kwargs):
        if "-I" not in command:
            return original(command, **kwargs)
        if failure == "timeout":
            return original([sys.executable, "-I", "-c", "import time; time.sleep(10)"],
                            **{**kwargs, "timeout": 0.05})
        if failure in ("nonzero", "dependency", "killed"):
            code = {
                "nonzero": "import sys; print('PASS (must not leak)'); sys.exit(7)",
                "dependency": "import missing_remora_test_dependency",
                "killed": "import os, signal; os.kill(os.getpid(), signal.SIGKILL)",
            }[failure]
            return original([sys.executable, "-I", "-c", code], **kwargs)
        if failure == "malformed":
            return subprocess.CompletedProcess(command, 0, '{"cases": []}', "")
        payload = json.loads(original(command, **kwargs).stdout)
        payload["cases"][runner.CONTRACTS[0]][0]["unexpected_field"] = True
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner.subprocess, "run", force_failure)
    exit_code = runner.main(["--revision", revision, "--operator", "test operator",
                             "--host", "test host", "--output", str(output)])
    captured = capsys.readouterr()
    assert exit_code != 0, "verifier_failure_exit_nonzero"
    assert not output.exists(), "no_report_on_failure"
    assert "PASS" not in captured.out, "no_pass_on_failure"
    assert "no result published" in captured.err
    assert json.loads(captured.err)["execution_status"] == "FAILED"
    assert not list(tmp_path.glob(".remora-result-*"))


def test_actual_missing_dependency_fails_closed(pinned, tmp_path):
    root, revision = pinned
    output = tmp_path / "report.json"
    result = subprocess.run([sys.executable, "-S", *_arguments(root, revision, output)[1:]],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists()
    assert "PASS" not in result.stdout
    assert "no result published" in result.stderr


def test_existing_output_refused_even_if_empty(pinned, tmp_path):
    root, revision = pinned
    output = tmp_path / "existing.json"
    output.write_text("operator-owned")
    result = subprocess.run(_arguments(root, revision, output), capture_output=True, text=True)
    assert result.returncode != 0
    assert output.read_text() == "operator-owned"
    assert "PASS" not in result.stdout
    assert "existing output refused" in result.stderr


def test_broken_symlink_output_refused(pinned, tmp_path):
    root, revision = pinned
    output = tmp_path / "existing.json"
    output.symlink_to(tmp_path / "missing")
    with pytest.raises(runner.RunnerError, match="existing output refused"):
        runner.run(root, revision, list(runner.CONTRACTS), output, "test", 120, "test host")
    assert output.is_symlink()


@pytest.mark.parametrize("revision", ["master", "a" * 40])
def test_revision_mismatch_refused(pinned, tmp_path, revision):
    root, _ = pinned
    with pytest.raises(runner.RunnerError, match="revision"):
        runner.run(root, revision, list(runner.CONTRACTS), tmp_path / "report.json", "test", 120, "test host")
    assert not (tmp_path / "report.json").exists()


def test_dirty_tracked_source_refused(pinned, tmp_path):
    root, revision = pinned
    path = root / "remora/interop/boundary_fixtures.py"
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n# dirty runtime\n")
        with pytest.raises(runner.RunnerError, match="differ from"):
            runner.run(root, revision, list(runner.CONTRACTS), tmp_path / "report.json", "test", 120, "test host")
    finally:
        path.write_bytes(original)
    assert not (tmp_path / "report.json").exists()


def test_untracked_runtime_module_is_never_copied(pinned, tmp_path):
    root, revision = pinned
    path = root / "remora/interop/foreign_untracked.py"
    try:
        path.write_text('raise RuntimeError("should not run")\n')
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        digests = runner._snapshot(root, revision, snapshot)
        assert path.relative_to(root).as_posix() not in digests
        assert not (snapshot / path.relative_to(root)).exists()
    finally:
        path.unlink()


def test_package_bytes_checked_before_runtime(pinned, tmp_path):
    root, revision = pinned
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    digests = runner._snapshot(root, revision, snapshot)
    fixture = snapshot / "artifacts/interop/exact-call-binding-v1/fixtures.json"
    fixture.write_text("{}")
    with pytest.raises(runner.RunnerError, match="digest mismatch"):
        runner._packages(snapshot, list(runner.CONTRACTS), digests)


@pytest.mark.parametrize("change", [
    "missing_case", "duplicate_case", "false_status", "wrong_expected", "wrong_digest",
    "missing_presentation", "malformed_outcome", "malformed_effect",
])
def test_malformed_results_fail_closed(pinned, tmp_path, change):
    root, revision = pinned
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    digests = runner._snapshot(root, revision, snapshot)
    packages = runner._packages(snapshot, list(runner.CONTRACTS), digests)
    observed = subprocess.run(
        [sys.executable, "-I", "-B", str(snapshot / runner.SCRIPT), "--worker", *runner.CONTRACTS],
        cwd=tmp_path, env=runner._environment(tmp_path), capture_output=True, text=True, check=True,
        input=runner._json(digests),
    )
    payload = json.loads(observed.stdout)
    cases = payload["cases"][runner.CONTRACTS[0]]
    if change == "missing_case":
        cases.pop()
    elif change == "duplicate_case":
        cases[1] = copy.deepcopy(cases[0])
    elif change == "false_status":
        cases[0]["result"] = "NOT_ESTABLISHED"
    elif change == "wrong_expected":
        cases[0]["expected"] = {"value": False}
    elif change == "wrong_digest":
        payload["runtime_modules"]["remora/interop/boundary_fixtures.py"] = "sha256:" + "0" * 64
    elif change == "missing_presentation":
        cases[0]["observed"] = {"value": []}
        cases[0]["result"] = "CONTRADICTED"
    elif change == "malformed_outcome":
        cases[0]["observed"]["value"][0]["outcome"] = True
        cases[0]["result"] = "CONTRADICTED"
    else:
        case = payload["cases"]["effect-evidence-v1"][0]
        case["observed"]["value"]["effect_status"] = None
        case["result"] = "CONTRADICTED"
    with pytest.raises(runner.RunnerError):
        runner._validate_observations(payload, packages, digests)


def test_completed_contradiction_is_preserved_not_runner_failure(pinned, tmp_path, monkeypatch):
    root, revision = pinned
    original = subprocess.run

    def contradict(command, **kwargs):
        result = original(command, **kwargs)
        if "-I" in command:
            payload = json.loads(result.stdout)
            case = payload["cases"][runner.CONTRACTS[0]][0]
            case["observed"]["value"][0] = {"outcome": "REFUSED", "refusal_class": "injected_disagreement"}
            case["result"] = "CONTRADICTED"
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        return result

    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner.subprocess, "run", contradict)
    output = tmp_path / "negative-result.json"
    assert runner.main(["--revision", revision, "--operator", "test",
                        "--host", "test host", "--output", str(output)]) == 1
    case = json.loads(output.read_text())["contracts"][0]["cases"][0]
    assert case["claim_status"] == "CONTRADICTED"


def test_concurrent_publication_cannot_overwrite(pinned, tmp_path, monkeypatch):
    root, revision = pinned
    output = tmp_path / "result.json"
    original = os.link

    def competing_writer(source, target):
        output.write_text("other operator's result")
        return original(source, target)

    monkeypatch.setattr(runner.os, "link", competing_writer)
    with pytest.raises(FileExistsError):
        runner.run(root, revision, list(runner.CONTRACTS), output, "test", 120, "test host")
    assert output.read_text() == "other operator's result"
    assert not list(tmp_path.glob(".remora-result-*"))


def test_dependency_free_discovery():
    result = subprocess.run([sys.executable, "-S", str(runner.ROOT / runner.SCRIPT), "--list"],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["contracts"] == list(runner.CONTRACTS)


@pytest.mark.parametrize("value", [
    '{"cases": {}, "cases": {}}', '{"value": NaN}', '{"value": Infinity}',
    '{"value": 1e400}', '{"value": -1e400}',
])
def test_duplicate_or_nonfinite_json_refused(value):
    with pytest.raises(runner.RunnerError):
        runner._decode(value)


def test_same_pinned_revision_has_identical_normalized_observation(pinned, tmp_path):
    root, revision = pinned
    reports = []
    for index in range(2):
        output = tmp_path / f"run-{index}.json"
        assert runner.run(root, revision, list(runner.CONTRACTS), output,
                          f"operator-{index}", 120, "same host") == 3
        report = json.loads(output.read_text())
        reports.append({key: value for key, value in report.items()
                        if key not in {"started_at", "completed_at", "operator_declaration"}})
    assert reports[0] == reports[1]


@pytest.mark.parametrize("stage", ["before_worker_read", "after_worker_result"])
def test_input_toctou_cannot_publish_success(pinned, tmp_path, monkeypatch, capsys, stage):
    root, revision = pinned
    original = subprocess.run

    def change_snapshot(command, **kwargs):
        if "-I" not in command:
            return original(command, **kwargs)
        fixture = kwargs["cwd"] / "source/artifacts/interop/exact-call-binding-v1/fixtures.json"
        if stage == "before_worker_read":
            fixture.write_text("{}")
            return original(command, **kwargs)
        result = original(command, **kwargs)
        fixture.write_text("{}")
        return result

    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner.subprocess, "run", change_snapshot)
    output = tmp_path / "result.json"
    assert runner.main(["--revision", revision, "--operator", "test", "--host", "test",
                        "--output", str(output)]) == 2
    captured = capsys.readouterr()
    assert "digest mismatch" in captured.err
    assert not output.exists()
    assert "PASS" not in captured.out


def test_fixture_is_parsed_from_the_same_validated_bytes(pinned, tmp_path, monkeypatch):
    root, revision = pinned
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    digests = runner._snapshot(root, revision, snapshot)
    original = runner._read_snapshot
    relative = "artifacts/interop/exact-call-binding-v1/fixtures.json"

    def mutate_after_read(source, name, pins):
        data = original(source, name, pins)
        if name == relative:
            (source / name).write_text("{}")
        return data

    monkeypatch.setattr(runner, "_read_snapshot", mutate_after_read)
    package, = runner._packages(snapshot, ["exact-call-binding-v1"], digests)
    assert package["fixtures"]["cases"]
    assert package["fixture_digest"] == digests[relative]
    with pytest.raises(runner.RunnerError, match="digest mismatch"):
        runner._verify_snapshot(snapshot, digests)


@pytest.mark.parametrize("kind", [
    "symlink", "nested_symlink", "hardlink", "parent_escape", "absolute", "alias",
])
def test_snapshot_path_and_link_attacks_refused(pinned, tmp_path, kind):
    root, revision = pinned
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    digests = runner._snapshot(root, revision, snapshot)
    relative = "artifacts/interop/exact-call-binding-v1/fixtures.json"
    target = snapshot / relative
    outside = tmp_path / "operator-controlled.json"
    outside.write_bytes(target.read_bytes())
    if kind == "symlink":
        target.unlink()
        target.symlink_to(outside)
    elif kind == "hardlink":
        target.unlink()
        os.link(outside, target)
    elif kind == "nested_symlink":
        directory = snapshot / "artifacts/interop/exact-call-binding-v1"
        directory.rename(snapshot / "saved-package")
        directory.symlink_to(snapshot / "saved-package", target_is_directory=True)
    elif kind == "parent_escape":
        relative = "../operator-controlled.json"
        digests[relative] = runner._digest(outside.read_bytes())
    elif kind == "absolute":
        relative = str(outside)
        digests[relative] = runner._digest(outside.read_bytes())
    else:
        relative = "artifacts/interop/exact-call-binding-v1/./fixtures.json"
        digests[relative] = runner._digest(outside.read_bytes())
    with pytest.raises(runner.RunnerError):
        runner._read_snapshot(snapshot, relative, digests)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "parent_escape"])
def test_archive_links_and_escape_refused(pinned, tmp_path, monkeypatch, kind):
    root, revision = pinned
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tree:
        item = tarfile.TarInfo("../outside.json" if kind == "parent_escape" else "remora/linked.py")
        item.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
        item.linkname = "/tmp/operator-controlled"
        tree.addfile(item)
    original = runner._git

    def altered_archive(source, *arguments):
        return archive.getvalue() if arguments[0] == "archive" else original(source, *arguments)

    monkeypatch.setattr(runner, "_git", altered_archive)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    with pytest.raises(runner.RunnerError):
        runner._snapshot(root, revision, snapshot)
