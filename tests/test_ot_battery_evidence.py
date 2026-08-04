import importlib.util
import json
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
