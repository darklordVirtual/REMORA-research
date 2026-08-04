import importlib.util
import json
import os
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "ot-pilot" / "run_ot_battery.py"
SPEC = importlib.util.spec_from_file_location("remora_ot_battery", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def test_build_evidence_bundle_writes_structured_artifact(tmp_path: Path) -> None:
    results = [
        {"name": "Case A", "ok": True, "decision": "accept", "outcome": "execute"},
        {"name": "Case B", "ok": False, "decision": "verify", "outcome": "abstain"},
    ]

    bundle = module.build_evidence_bundle(
        results=results,
        version={"runtime_mode": "pilot"},
        verify={"valid": True, "problems": []},
        control_plane_verify={"chain_valid": True, "records_checked": 3},
        metrics={"assess_total": 2},
    )

    assert bundle["summary"]["cases_passed"] == 1
    assert bundle["summary"]["cases_failed"] == 1
    assert bundle["results"][0]["name"] == "Case A"

    artifact_path = tmp_path / "ot-evidence.json"
    module.write_evidence_bundle(bundle, artifact_path)

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["summary"]["cases_failed"] == 1
    assert payload["audit"]["tenant_chain_valid"] is True


def _bundle(run_id: str) -> dict:
    return module.build_evidence_bundle(
        results=[{"name": "Case A", "ok": True, "decision": "verify"}],
        run_id=run_id,
    )


def test_write_run_directory_layout(tmp_path: Path) -> None:
    layout = module.write_run_directory(_bundle("run-layout"), tmp_path)

    run_dir = Path(layout["run_dir"])
    assert run_dir.name == "run-layout"
    for name in ("manifest.json", "results.json", "metrics.json",
                 "chain-verification.json", "report.txt"):
        assert (run_dir / name).exists(), f"missing {name}"

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "run-layout"
    report = (run_dir / "report.txt").read_text(encoding="utf-8")
    assert "run-layout" in report


def _seed_runs(base: Path, names: list[str]) -> None:
    """Create run dirs whose mtimes strictly increase in list order."""
    start = 1_700_000_000
    for i, name in enumerate(names):
        module.write_run_directory(_bundle(name), base)
        os.utime(base / name, (start + i * 60, start + i * 60))


def test_prune_evidence_runs_keeps_newest(tmp_path: Path) -> None:
    _seed_runs(tmp_path, ["run-1", "run-2", "run-3", "run-4", "run-5"])

    removed = module.prune_evidence_runs(tmp_path, keep=2)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["run-4", "run-5"]
    assert sorted(Path(r).name for r in removed) == ["run-1", "run-2", "run-3"]


def test_prune_evidence_runs_disabled_when_keep_not_positive(tmp_path: Path) -> None:
    _seed_runs(tmp_path, ["run-1", "run-2"])

    assert module.prune_evidence_runs(tmp_path, keep=0) == []
    assert module.prune_evidence_runs(tmp_path, keep=-3) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["run-1", "run-2"]


def test_prune_evidence_runs_missing_root_is_noop(tmp_path: Path) -> None:
    assert module.prune_evidence_runs(tmp_path / "absent", keep=5) == []
