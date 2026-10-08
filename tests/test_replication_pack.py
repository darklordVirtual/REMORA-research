# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The replication pack verifies what it says it verifies, and cannot drift.

scripts/verify_replication_pack.py --check must pass on the committed tree,
must fail when an artifact or a metric value is tampered with, and must fail
when the pack stops agreeing with the claim register or the results
manifest. Tampering happens on copies under tmp_path, never on the real
files.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_replication_pack as vrp  # noqa: E402

PACK_PATH = ROOT / vrp.PACK
REGISTER = ROOT / "docs" / "assurance" / "claim_register_v1.yaml"
ARTIFACT_MANIFEST = ROOT / "docs" / "assurance" / "artifact_manifest_v1.md"


def _pack() -> dict:
    return json.loads(PACK_PATH.read_text(encoding="utf-8"))


def _files_the_check_reads(pack: dict) -> set[str]:
    files = {str(vrp.PACK), pack["environment"]["requirements_lock"]["path"],
             pack["environment"]["reference_image"]["dockerfile"],
             pack["sources"]["claim_register"], pack["sources"]["results_manifest"]}
    for entry in pack["entries"]:
        files |= {a["path"] for a in entry["artifacts"]}
        files |= {p["file"] for p in entry.get("integrity", []) if "file" in p}
    return files


@pytest.fixture()
def copy_root(tmp_path: Path) -> Path:
    for rel in _files_the_check_reads(_pack()):
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    return tmp_path


def _check(root: Path) -> vrp.Report:
    report = vrp.Report()
    pack = json.loads((root / vrp.PACK).read_text(encoding="utf-8"))
    vrp.run_check(pack, root, report)
    return report


def _failed(report: vrp.Report) -> list[tuple[str, ...]]:
    return report.failures


def _rewrite_pack(root: Path, edit) -> None:
    path = root / vrp.PACK
    pack = json.loads(path.read_text(encoding="utf-8"))
    edit(pack)
    path.write_text(json.dumps(pack, indent=2), encoding="utf-8")


def _entry(pack: dict, claim_id: str) -> dict:
    return next(e for e in pack["entries"] if e["claim_id"] == claim_id)


# -- the committed pack ------------------------------------------------------


def test_committed_pack_passes_check(capsys):
    assert vrp.main(["--check"]) == 0
    assert "[PASS] replication pack" in capsys.readouterr().out


def test_copied_tree_passes_check(copy_root):
    assert _failed(_check(copy_root)) == []


def test_headline_claims_are_in_the_pack():
    ids = {e["claim_id"] for e in _pack()["entries"]}
    assert {"CLAIM-001", "CLAIM-002", "CLAIM-003", "CLAIM-019"} <= ids


# -- tampering fails ---------------------------------------------------------


def test_tampered_artifact_fails_its_hash(copy_root):
    target = copy_root / "results" / "external_benchmark_agentharm_v1.json"
    target.write_bytes(target.read_bytes() + b" ")
    failed = _failed(_check(copy_root))
    assert ("CLAIM-002", "sha256") in {(r[0], r[1]) for r in failed}


def test_tampered_expected_hash_fails(copy_root):
    def edit(pack):
        _entry(pack, "CLAIM-019")["artifacts"][0]["sha256_lf"] = "0" * 64
    _rewrite_pack(copy_root, edit)
    failed = _failed(_check(copy_root))
    assert [r[:3] for r in failed] == [
        ("CLAIM-019", "sha256", "results/routing_bench_bfcl_v4_cext3_results.json")]


def test_changed_metric_value_in_artifact_fails_the_metric(copy_root):
    # Change the number and re-pin the hash, so that only the metric check
    # stands between the edit and a pass.
    rel = "results/external_benchmark_agentharm_v1.json"
    data = json.loads((copy_root / rel).read_text(encoding="utf-8"))
    data["false_accept_rate"] = 0.01
    (copy_root / rel).write_text(json.dumps(data), encoding="utf-8")
    new_hash = vrp.sha256_lf(copy_root / rel)

    def edit(pack):
        _entry(pack, "CLAIM-002")["artifacts"][0]["sha256_lf"] = new_hash
    _rewrite_pack(copy_root, edit)
    failed = _failed(_check(copy_root))
    assert [(r[0], r[2]) for r in failed] == [("CLAIM-002", "far_pct")]


def test_changed_expected_metric_in_pack_fails(copy_root):
    def edit(pack):
        metric = next(m for m in _entry(pack, "CLAIM-019")["metrics"]
                      if m["name"] == "obtainable_verify_pct")
        metric["expected"] = 46.8
    _rewrite_pack(copy_root, edit)
    failed = _failed(_check(copy_root))
    assert ("CLAIM-019", "obtainable_verify_pct") in {(r[0], r[2]) for r in failed}


def test_broken_sealed_manifest_pin_fails(copy_root):
    holdout = copy_root / "data" / "routing_bench_bfcl_v4_cext3" / "bfcl_holdout.jsonl"
    holdout.write_bytes(holdout.read_bytes() + b"\n")
    checks = {(r[0], r[1], r[2]) for r in _failed(_check(copy_root))}
    assert ("CLAIM-019", "integrity", "data/routing_bench_bfcl_v4_cext3/bfcl_holdout.jsonl") in checks


def test_advisory_pin_warns_without_failing(copy_root):
    bundle = copy_root / "remora" / "toolcall" / "routing" / "goal_match.py"
    bundle.write_text(bundle.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    report = _check(copy_root)
    assert _failed(report) == []
    assert any(r[-1] == "WARN" and r[2].endswith("goal_match.py") for r in report.rows)


# -- environment -------------------------------------------------------------


def test_changed_lockfile_fails(copy_root):
    lock = copy_root / "requirements-lock.txt"
    lock.write_text(lock.read_text(encoding="utf-8") + "extra==1.0\n", encoding="utf-8")
    assert ("env", "sha256") in {(r[0], r[1]) for r in _failed(_check(copy_root))}


def test_unpinned_base_image_fails(copy_root):
    dockerfile = copy_root / "deploy" / "reference" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    dockerfile.write_text(re.sub(r"@sha256:[0-9a-f]{64}", "", text, count=1), encoding="utf-8")
    assert ("env", "base image") in {(r[0], r[1]) for r in _failed(_check(copy_root))}


def test_pack_claims_no_image_digest_it_cannot_prove():
    env = _pack()["environment"]
    assert env["image"] is None
    assert env["image_reason"].strip()
    digest = env["reference_image"]["base_digest"]
    text = (ROOT / env["reference_image"]["dockerfile"]).read_text(encoding="utf-8")
    assert digest in text


def test_a_claimed_image_digest_fails(copy_root):
    _rewrite_pack(copy_root, lambda p: p["environment"].update(image="remora@sha256:" + "a" * 64))
    assert ("env", "image") in {(r[0], r[1]) for r in _failed(_check(copy_root))}


# -- the pack cannot drift from the register ----------------------------------


def _bound(claim: dict) -> bool:
    return any(isinstance(b, dict) and ("path" in b or "derived" in b)
               for b in (claim.get("metric_bindings") or {}).values())


def test_every_machine_bound_active_claim_is_in_the_pack():
    register = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    pack = _pack()
    in_pack = {e["claim_id"] for e in pack["entries"]}
    excluded = {e["claim_id"]: e["reason"] for e in pack["excluded"]}
    for claim in register["claims"]:
        if claim.get("status") != "active":
            continue
        cid = claim["id"]
        if _bound(claim):
            assert cid in in_pack, f"{cid} has machine-bound metrics but is not in the pack"
        else:
            assert cid in in_pack or excluded.get(cid, "").strip(), \
                f"{cid} is active but neither in the pack nor excluded with a reason"


def test_dropping_an_entry_is_caught_as_drift(copy_root):
    _rewrite_pack(copy_root, lambda p: p.update(
        entries=[e for e in p["entries"] if e["claim_id"] != "CLAIM-020"]))
    failed = _failed(_check(copy_root))
    assert any(r[0] == "CLAIM-020" and r[1] == "drift (coverage)" for r in failed)


def test_excluding_a_machine_bound_claim_is_caught(copy_root):
    def edit(pack):
        pack["entries"] = [e for e in pack["entries"] if e["claim_id"] != "CLAIM-005"]
        pack["excluded"].append({"claim_id": "CLAIM-005", "reason": "too slow"})
    _rewrite_pack(copy_root, edit)
    failed = _failed(_check(copy_root))
    assert any(r[0] == "CLAIM-005" and "machine-bound" in r[3] for r in failed)


def test_register_value_change_is_caught_as_drift(copy_root):
    register = copy_root / "docs" / "assurance" / "claim_register_v1.yaml"
    text = register.read_text(encoding="utf-8")
    assert "      legitimate_read_autonomy_pct: 26.6\n" in text
    register.write_text(text.replace("      legitimate_read_autonomy_pct: 26.6\n",
                                     "      legitimate_read_autonomy_pct: 26.7\n"), encoding="utf-8")
    failed = _failed(_check(copy_root))
    assert any(r[0] == "CLAIM-019" and r[1] == "drift (metric)" for r in failed)


def test_results_manifest_class_change_is_caught(copy_root):
    manifest = copy_root / "docs" / "assurance" / "results_manifest_v1.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    for entry in data["results"]:
        if entry["path"] == "results/false_accept_regression_v1.json":
            entry["class"] = "live"
            entry["generator"] = "python x.py"
    manifest.write_text(yaml.safe_dump(data), encoding="utf-8")
    failed = _failed(_check(copy_root))
    assert any(r[0] == "CLAIM-003" and r[1] == "drift (class)" for r in failed)


def test_pack_hashes_agree_with_the_artifact_manifest():
    """Where artifact_manifest_v1.md pins a file, the pack pins the same bytes."""
    rows = re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|",
                      ARTIFACT_MANIFEST.read_text(encoding="utf-8"), re.MULTILINE)
    pinned = dict(rows)
    compared = 0
    for entry in _pack()["entries"]:
        for art in entry["artifacts"]:
            if art["path"] in pinned:
                assert art["sha256_lf"] == pinned[art["path"]], art["path"]
                compared += 1
    assert compared >= 5


def test_every_regenerate_command_names_its_source():
    for entry in _pack()["entries"]:
        regen = entry["regenerate"]
        assert regen["mode"] in {"regenerate", "validate", "none"}
        assert regen["reason"].strip()
        if regen["mode"] == "none":
            assert not regen["commands"] and not regen["compare"]
        else:
            assert regen["commands"]
        for command in regen["commands"]:
            assert command["source"] in {"register reproduce", "results manifest generator"}
        for cmp in regen["compare"]:
            assert cmp["match"] in {"lf_sha256", "fields"}


def test_register_reproduce_commands_are_used_verbatim():
    """A command sourced from the register must appear in that claim's reproduce text."""
    register = {c["id"]: c for c in yaml.safe_load(REGISTER.read_text(encoding="utf-8"))["claims"]}
    for entry in _pack()["entries"]:
        reproduce = " ".join(str(register[entry["claim_id"]].get("reproduce", "")).split())
        for command in entry["regenerate"]["commands"]:
            if command["source"] == "register reproduce":
                core = command["run"].replace(" -q -p no:cacheprovider", "")
                assert core in reproduce, (entry["claim_id"], command["run"])


# -- --regenerate --------------------------------------------------------------


def test_regenerate_reproduces_a_deterministic_entry_in_a_throwaway_worktree():
    """One cheap entry end to end: run in a worktree of HEAD, compare, clean up."""
    if not (ROOT / ".git").exists():
        pytest.skip("--regenerate needs a git checkout")
    pack = _pack()
    pack["entries"] = [_entry(pack, "CLAIM-005")]
    report = vrp.Report()
    vrp.run_regenerate(pack, ROOT, report)
    checks = {(r[1], r[-1]) for r in report.rows}
    assert ("run", "OK") in checks
    assert ("compare lf_sha256", "OK") in checks
    assert ("regenerated metric", "OK") in checks
    assert report.failures == []


# -- metric arithmetic ---------------------------------------------------------


def test_rounded_binding_compares_at_the_published_precision():
    assert vrp.metric_matches(1.4, 1.428571, {"rounded_to": 1}, 5e-3)
    assert not vrp.metric_matches(1.5, 1.428571, {"rounded_to": 1}, 5e-3)


def test_bool_metric_must_be_equal():
    assert vrp.metric_matches(True, True, {}, 5e-3)
    assert not vrp.metric_matches(True, 1.0, {}, 5e-3)


def test_lf_hash_ignores_crlf(tmp_path):
    lf, crlf = tmp_path / "a", tmp_path / "b"
    lf.write_bytes(b"x\ny\n")
    crlf.write_bytes(b"x\r\ny\r\n")
    assert vrp.sha256_lf(lf) == vrp.sha256_lf(crlf) == hashlib.sha256(b"x\ny\n").hexdigest()


# ── --refresh-lock: one command after a dependency change ────────────────────

def _git(root: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=root, check=True, capture_output=True)


@pytest.fixture()
def git_copy_root(copy_root: Path) -> Path:
    _git(copy_root, "init", "-q")
    _git(copy_root, "add", "-A")
    _git(copy_root, "commit", "-q", "-m", "pinned")
    return copy_root


def _bump_lock(root: Path) -> None:
    lock = root / "requirements-lock.txt"
    lock.write_text(lock.read_text(encoding="utf-8") + "extra==1.0\n", encoding="utf-8")


def test_refresh_lock_pins_the_new_lock_and_keeps_the_old_pin(git_copy_root, capsys):
    root = git_copy_root
    before = json.loads((root / vrp.PACK).read_text(encoding="utf-8"))["environment"]
    _bump_lock(root)
    assert vrp.main(["--refresh-lock", "--reason", "extra 1.0 (#1)", "--root", str(root)]) == 0
    assert "[PASS] replication pack" in capsys.readouterr().out
    env = json.loads((root / vrp.PACK).read_text(encoding="utf-8"))["environment"]
    assert env["requirements_lock"]["sha256_lf"] == vrp.sha256_lf(root / "requirements-lock.txt")
    head = env["requirements_lock_history"][0]
    assert head["sha256_lf"] == before["requirements_lock"]["sha256_lf"]
    assert head["reason"] == "extra 1.0 (#1)" and len(head["git_revision"]) == 40
    assert env["requirements_lock_history"][1:] == before["requirements_lock_history"]


def test_refresh_lock_is_a_no_op_when_the_lock_is_unchanged(git_copy_root, capsys):
    pack = (git_copy_root / vrp.PACK).read_bytes()
    assert vrp.main(["--refresh-lock", "--reason", "r", "--root", str(git_copy_root)]) == 0
    assert "nothing to pin" in capsys.readouterr().out
    assert (git_copy_root / vrp.PACK).read_bytes() == pack


def test_refresh_lock_needs_a_reason(git_copy_root):
    _bump_lock(git_copy_root)
    pack = (git_copy_root / vrp.PACK).read_bytes()
    assert vrp.main(["--refresh-lock", "--root", str(git_copy_root)]) == 1
    assert (git_copy_root / vrp.PACK).read_bytes() == pack


def test_refresh_lock_refuses_an_old_pin_no_commit_matches(git_copy_root):
    root = git_copy_root
    pack = json.loads((root / vrp.PACK).read_text(encoding="utf-8"))
    pack["environment"]["requirements_lock"]["sha256_lf"] = "0" * 64
    _bump_lock(root)
    with pytest.raises(vrp.PackError, match="cannot be placed in history"):
        vrp.refresh_lock(pack, root, "r")


def test_refreshing_writes_the_pack_byte_for_byte_in_its_own_format(git_copy_root):
    root = git_copy_root
    _bump_lock(root)
    vrp.main(["--refresh-lock", "--reason", "r", "--root", str(root)])
    text = (root / vrp.PACK).read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), indent=2) + "\n"
    assert "\r\n" not in (root / vrp.PACK).read_bytes().decode("utf-8")
