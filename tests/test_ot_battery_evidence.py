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


def test_envelope_chain_breaks_reach_the_bundle() -> None:
    """/v1/audit/chain/verify reports break details under `breaks`; the bundle
    must carry them, not silently record an empty problems list."""
    bundle = module.build_evidence_bundle(
        results=[{"name": "Case A", "ok": True}],
        verify={"valid": True, "problems": ["execution_gap_at:3"]},
        control_plane_verify={"chain_valid": False, "records_checked": 4,
                              "breaks": ["hash_mismatch_at:2"]},
    )

    assert bundle["envelope_chain"]["valid"] is False
    assert bundle["envelope_chain"]["problems"] == ["hash_mismatch_at:2"]
    assert bundle["audit"]["problems"] == ["execution_gap_at:3", "hash_mismatch_at:2"]


def test_governance_hashes_come_from_measured_semantics() -> None:
    """SHELF-020 semantic hashes exist per assess result; the bundle must
    record them instead of hardcoding None."""
    results = [
        {"name": "Case A", "ok": True, "semantic": {
            "tool_contract_bundle_hash": "f6d74252", "intent_authority_hash": "b32f50e0"}},
        {"name": "Case B", "ok": True},
    ]

    bundle = module.build_evidence_bundle(results=results)

    assert bundle["governance"]["tool_contract_bundle_hash"] == "f6d74252"
    assert bundle["governance"]["intent_authority_hash"] == "b32f50e0"


def test_dirty_worktree_is_unknown_not_asserted_clean() -> None:
    """The battery runs where git is unavailable; provenance it cannot
    measure must be recorded as unknown (None), never asserted False."""
    bundle = module.build_evidence_bundle(results=[{"name": "Case A", "ok": True}])

    assert bundle["source"]["dirty_worktree"] is None


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


def test_a_named_refusal_at_assess_is_a_refusal_not_an_http_error() -> None:
    """Cumulative limits refuse at assess with 409 and a named reason before
    any decision. Until 2026-10-25 the battery reported that as an HTTP error
    and three cases failed although the system did what they expected."""
    refused = module.Case("Limit", "refused", "adjust_setpoint", {}, refusal="limit_exceeded")
    rec = {"outcome": "refused_at_assess", "refusal": "limit_exceeded", "decision": None}
    assert module.judge(refused, rec) is True
    assert module.judge(refused, {**rec, "refusal": "limit_coverage_unknown"}) is False
    assert module.judge(refused, {"decision": "verify"}) is False
    not_accepted = module.Case("Injection", "not_accepted", "set_valve_position", {})
    assert module.judge(not_accepted, rec) is True
    assert module.judge(not_accepted, {"decision": "escalate"}) is True
    assert module.judge(not_accepted, {"decision": "accept"}) is False
    assert module.judge(not_accepted, {"decision": None, "outcome": "http_error"}) is False


def test_the_battery_names_its_limit_cases() -> None:
    by_name = {c.name: c for c in module.CASES}
    assert len(module.CASES) == 16
    assert by_name["Limit: PIC-101 move past its hourly movement cap"].refusal == "limit_exceeded"
    assert by_name["Unknown tool not in any registry"].refusal == "limit_coverage_unknown"
    assert by_name["Setpoint on a loop that does not exist"].refusal == "limit_observation_unavailable"
    assert by_name["Injection in maintenance document"].args["position_pct"] == 40


def test_monitoring_utility_is_not_the_policy_pass_rate() -> None:
    """Two safe VERIFY outcomes do not constitute two completed reads."""
    results = [
        {"tool": "read_sensor", "expect": "monitoring_read", "ok": True,
         "decision": "verify"},
        {"tool": "read_sensor", "expect": "monitoring_read", "ok": True,
         "decision": "accept", "outcome": "execute",
         "tool_execution": {"executed": True}},
        {"tool": "read_sensor", "expect": "monitoring_read", "ok": True,
         "decision": "accept", "outcome": "binding_refused",
         "tool_execution": {"executed": False}},
        {"tool": "adjust_setpoint", "expect": "executes", "ok": True,
         "decision": "verify", "tool_execution": {"executed": True}},
    ]
    bundle = module.build_evidence_bundle(results)
    utility = bundle["utility"]
    assert bundle["summary"]["cases_passed"] == 4
    assert utility == {
        "monitoring_reads_total": 3,
        "monitoring_reads_accepted": 2,
        "monitoring_reads_review_required": 1,
        "monitoring_reads_completed": 1,
        "monitoring_reads_unfinished": 2,
        "monitoring_read_completion_rate": 1 / 3,
    }
    assert "Monitoring reads completed: 1/3" in module.render_text_report(bundle)


def test_direct_accepted_read_redeems_once(monkeypatch) -> None:
    """When policy eventually grounds reads, the battery tests real dispatch."""
    seen: list[str] = []

    def fake_call(method, path, token, body=None):
        seen.append(path)
        if path == "/v1/execution/assess":
            return 200, {"decision": "accept", "reasons": [], "semantic": {},
                         "execution_token": {"jti": "read-1"}}
        if path == "/v1/execution/execute-accepted":
            assert body["execution_token"]["jti"] == "read-1"
            if seen.count(path) == 1:
                return 200, {"outcome": "execute",
                             "tool_execution": {"executed": True}}
            return 409, {"detail": "token_already_consumed"}
        raise AssertionError(path)

    monkeypatch.setattr(module, "call", fake_call)
    case = module.Case("sensor", "monitoring_read", "read_sensor",
                       {"sensor_id": "PT-101"}, intent_ref="MON-ROUND")
    records: list[dict] = []
    result = module.run_case(case, records)
    assert result["ok"] is True
    assert result["replay_status"] == 409
    assert module.summarize_monitoring_utility(records)["monitoring_reads_completed"] == 1


def test_missing_accept_grant_never_counts_as_utility(monkeypatch) -> None:
    def fake_call(method, path, token, body=None):
        assert path == "/v1/execution/assess"
        return 200, {"decision": "accept", "reasons": [], "semantic": {},
                     "execution_token": None}

    monkeypatch.setattr(module, "call", fake_call)
    rec = module.run_case(
        module.Case("sensor", "monitoring_read", "read_sensor",
                    {"sensor_id": "PT-101"}), [],
    )
    assert rec["ok"] is False
    assert rec["outcome"] == "missing_execution_token"


def test_monitoring_utility_without_read_cases_is_not_a_fake_rate() -> None:
    utility = module.summarize_monitoring_utility([{"tool": "write", "ok": True}])
    assert utility["monitoring_reads_total"] == 0
    assert utility["monitoring_read_completion_rate"] is None
