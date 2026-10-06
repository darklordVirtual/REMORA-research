# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Admission verifies data against base trust without executing submitted code."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

from remora.interop.evidence_io import EvidenceError
from scripts import interop_external_admission as admission
from scripts import interop_operator_statement as signer
from scripts import interop_self_service as runner

OPERATOR = "operator:outside-fixture"
DIRECTORY = "artifacts/interop/submissions/fixture-run"


def _commit(root):
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(root), "-c", "user.name=Admission fixture",
        "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
        "-c", "core.hooksPath=/dev/null", "commit", "-qm",
        "Admission test data\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>",
    ], check=True)
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"]).decode().strip()


@pytest.fixture(scope="module")
def context(interop_pinned_repo, tmp_path_factory):
    source, _ = interop_pinned_repo
    work = tmp_path_factory.mktemp("admission-base")
    root = work / "base"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(source), str(root)], check=True)
    key = Ed25519PrivateKey.generate()
    private = work / "private.pem"
    private.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    private.chmod(0o600)
    key_id, _ = signer._public_identity(key.public_key())
    operators = json.loads((root / admission.REGISTRY).read_text())
    operators["operators"] = [{
        "operator_identity": OPERATOR, "key_id": key_id,
        "public_key_pem": key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode(),
        "relationship_to_producer": "EXTERNAL", "revoked": False,
        "allowed_scope": "pinned_runtime_primitive_fixtures",
    }]
    (root / admission.REGISTRY).write_text(json.dumps(operators))
    base = _commit(root)
    observation = work / "observation.json"
    assert runner.run(root, base, list(runner.CONTRACTS), observation, OPERATOR, 120, "fixture host") == 3
    statement = work / "operator-statement.json"
    signer.sign(observation, private, OPERATOR, statement)
    return root, base, private, observation, statement


@pytest.fixture
def submission(context, tmp_path):
    source, base, private, observation, statement = context
    root = tmp_path / "incoming"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(source), str(root)], check=True)
    directory = root / DIRECTORY
    directory.mkdir(parents=True)
    shutil.copyfile(observation, directory / "observation.json")
    shutil.copyfile(statement, directory / "operator-statement.json")
    descriptor = {
        "schema_version": "remora-interop-submission-v1", "operator_identity": OPERATOR,
        "observation": "observation.json", "operator_statement": "operator-statement.json",
        "boundary_digest": json.loads(observation.read_text())["boundary"]["register_digest"],
        "independence": "NOT_CLASSIFIED", "requested_admission": "REVIEW_ONLY",
    }
    (directory / "submission.json").write_text(json.dumps(descriptor))
    return root, base, private, directory


def test_positive_admission_never_reruns_or_admits(submission, monkeypatch):
    root, base, _, _ = submission
    head = _commit(root)
    original = subprocess.run

    def only_git(command, **kwargs):
        assert command[0] == "git", "admission must not launch runtime or verifier code"
        return original(command, **kwargs)

    def no_worker(*args, **kwargs):
        pytest.fail("admission executed a worker")

    monkeypatch.setattr(admission.runtime.subprocess, "run", only_git)
    monkeypatch.setattr(admission.runtime, "_worker", no_worker)
    result = admission.validate(root, base, head, DIRECTORY)
    assert result["validation_status"] == "VALIDATED_FOR_REVIEW"
    assert result["operator_role"] == "EXTERNAL"
    assert result["trust_revision"] == base
    assert result["runtime_rerun"] is False
    assert result["admission"] == "UNADMITTED"
    assert result["independence"] == "NOT_CLASSIFIED"
    assert result["confers_authority"] is False


def test_signed_negative_observation_remains_reviewable(submission):
    root, base, private, directory = submission
    observation = directory / "observation.json"
    report = json.loads(observation.read_text())
    case = report["contracts"][0]["cases"][0]
    case["observed"]["value"][0] = {"outcome": "REFUSED", "refusal_class": "fixture_disagreement"}
    case["claim_status"] = "CONTRADICTED"
    observation.write_text(json.dumps(report))
    signed = directory / "operator-statement.json"
    signed.unlink()
    signer.sign(observation, private, OPERATOR, signed)
    original = observation.read_bytes()
    result = admission.validate(root, base, _commit(root), DIRECTORY)
    assert result["validation_status"] == "VALIDATED_FOR_REVIEW"
    assert result["admission"] == "UNADMITTED"
    assert observation.read_bytes() == original
    assert json.loads(observation.read_text())["contracts"][0]["cases"][0]["claim_status"] == "CONTRADICTED"


@pytest.mark.parametrize("change", [
    "claim_upgrade", "expected_value", "missing_case", "non_claims", "runner_digest",
    "boundary", "unknown_revision", "unreviewed_revision", "independence",
])
def test_signed_false_bindings_or_claim_upgrades_refused(submission, change):
    root, base, private, directory = submission
    observation = directory / "observation.json"
    report = json.loads(observation.read_text())
    if change == "claim_upgrade":
        case = next(c for p in report["contracts"] for c in p["cases"]
                    if c["claim_status"] == "NOT_ESTABLISHED")
        case["claim_status"] = "ESTABLISHED"
    elif change == "expected_value":
        report["contracts"][0]["cases"][0]["expected"]["value"][0]["outcome"] = "WRONG"
    elif change == "missing_case":
        report["contracts"][0]["cases"].pop()
    elif change == "non_claims":
        report["contracts"][0]["does_not_establish"] = ["unrelated caveat"]
    elif change == "runner_digest":
        report["source_files"][runner.SCRIPT] = "sha256:" + "f" * 64
    elif change == "boundary":
        descriptor = json.loads((directory / "submission.json").read_text())
        descriptor["boundary_digest"] = "sha256:" + "f" * 64
        (directory / "submission.json").write_text(json.dumps(descriptor))
    elif change == "unknown_revision":
        report["runtime_revision"] = "f" * 40
    elif change == "unreviewed_revision":
        report["runtime_revision"] = _commit(root)
    else:
        # A reported independence promotion is invalid even before signature admission.
        report["independence"] = "L3_INDEPENDENT_RECOMPUTATION"
    observation.write_text(json.dumps(report))
    signed = directory / "operator-statement.json"
    signed.unlink()
    if change == "independence":
        with pytest.raises(EvidenceError):
            signer.sign(observation, private, OPERATOR, signed)
        return
    signer.sign(observation, private, OPERATOR, signed)
    head = _commit(root)
    with pytest.raises(EvidenceError):
        admission.validate(root, base, head, DIRECTORY)


def test_pr_cannot_add_its_own_trusted_key(submission):
    root, _, _, directory = submission
    operators = json.loads((root / admission.REGISTRY).read_text())
    submitted_bytes = {path.name: path.read_bytes() for path in directory.iterdir()}
    for path in directory.iterdir():
        path.unlink()
    directory.rmdir()
    empty = {**operators, "operators": []}
    (root / admission.REGISTRY).write_text(json.dumps(empty))
    base = _commit(root)
    (root / admission.REGISTRY).write_text(json.dumps(operators))
    directory.mkdir()
    for name, data in submitted_bytes.items():
        (directory / name).write_bytes(data)
    assert admission.registry(root, base)["operators"] == []
    head = _commit(root)
    with pytest.raises(EvidenceError, match="key is absent"):
        admission.validate(root, base, head, DIRECTORY)


def test_revocation_is_read_from_base_not_head(submission):
    root, _, _, _ = submission
    registry_path = root / admission.REGISTRY
    operators = json.loads(registry_path.read_text())
    operators["operators"][0]["revoked"] = True
    registry_path.write_text(json.dumps(operators))
    base = _commit(root)
    operators["operators"][0]["revoked"] = False
    registry_path.write_text(json.dumps(operators))
    head = _commit(root)
    with pytest.raises(EvidenceError, match="revoked in the base"):
        admission.validate(root, base, head, DIRECTORY)


def test_git_symlink_submission_refused(submission, tmp_path):
    root, base, _, directory = submission
    observation = directory / "observation.json"
    outside = tmp_path / "outside.json"
    observation.rename(outside)
    observation.symlink_to(outside)
    head = _commit(root)
    with pytest.raises(EvidenceError, match="regular Git blob"):
        admission.validate(root, base, head, DIRECTORY)


def test_modified_pr_code_is_data_only(submission):
    root, base, _, _ = submission
    (root / runner.SCRIPT).write_text('raise RuntimeError("incoming code must not run")\n')
    (root / "remora/enforcement/lease.py").write_text('raise RuntimeError("incoming lease must not load")\n')
    head = _commit(root)
    assert admission.validate(root, base, head, DIRECTORY)["runtime_rerun"] is False


def test_cli_refuses_invalid_paths_and_reports_no_admission(submission, capsys):
    root, base, _, _ = submission
    head = _commit(root)
    assert admission.main(["--repo", str(root), "--base", base, "--head", head,
                           "--submission", "../outside"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["validation_status"] == "REFUSED"
