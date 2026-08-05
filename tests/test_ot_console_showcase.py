import importlib.util
import io
import json
import os
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy/ot-pilot/console/app.py"
SPEC = importlib.util.spec_from_file_location("remora_console_app", MODULE_PATH)
console_app = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(console_app)


class DummyResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        self.calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, headers=None):
        self.calls.append((url, headers))
        if url.endswith("/v1/health"):
            return DummyResponse(200, {"status": "ok", "version": "0.10.0"})
        if url.endswith("/v1/policy/version"):
            return DummyResponse(200, {"runtime_mode": "development", "policy_hash": "abc123"})
        if url.endswith("/v1/metrics"):
            return DummyResponse(200, {"assess_total": 7, "decision_counts": {"verify": 4, "escalate": 3}})
        if url.endswith("/v1/audit/chain/verify"):
            return DummyResponse(200, {"chain_valid": True, "records_checked": 3})
        raise AssertionError(f"unexpected URL: {url}")


def test_diagnostics_endpoint_collects_runtime_insights(monkeypatch):
    monkeypatch.setattr(console_app.httpx, "AsyncClient", DummyAsyncClient)
    client = TestClient(console_app.app)

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["health"]["status"] == "ok"
    assert payload["policy"]["runtime_mode"] == "development"
    assert payload["metrics"]["assess_total"] == 7
    assert payload["chain"]["chain_valid"] is True
    assert payload["summary"]["ready"] is True


def test_index_serves_built_ui_when_present(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pilot.html").write_text(
        "<!doctype html><title>REMORA — OT Pilot Console</title>", encoding="utf-8"
    )
    monkeypatch.setattr(console_app, "DIST", tmp_path)
    client = TestClient(console_app.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "OT Pilot Console" in response.text


def test_index_is_loud_when_ui_not_built(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(console_app, "DIST", tmp_path / "absent")
    client = TestClient(console_app.app)

    response = client.get("/")

    assert response.status_code == 503
    assert "pilot:build" in response.text


def _make_run(root: Path, run_id: str, mtime: int, *, exit_code: int = 0) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "remora-evidence-run-v1",
        "run_id": run_id,
        "started_at": "2026-08-04T00:00:00Z",
        "finished_at": "2026-08-04T00:01:00Z",
        "exit_code": exit_code,
        "summary": {"cases_total": 15, "cases_passed": 15, "cases_failed": 0},
        "audit": {"tenant_chain_valid": True, "execution_chain_valid": True},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "results.json").write_text('{"results": []}', encoding="utf-8")
    os.utime(run_dir, (mtime, mtime))


def test_evidence_runs_lists_newest_first(monkeypatch, tmp_path: Path) -> None:
    _make_run(tmp_path, "run-old", 1_700_000_000)
    _make_run(tmp_path, "run-new", 1_700_000_600, exit_code=1)
    monkeypatch.setenv("REMORA_EVIDENCE_ROOT", str(tmp_path))
    client = TestClient(console_app.app)

    response = client.get("/api/evidence/runs")

    assert response.status_code == 200
    payload = response.json()
    assert [r["run_id"] for r in payload["runs"]] == ["run-new", "run-old"]
    assert payload["runs"][0]["exit_code"] == 1
    assert payload["runs"][0]["summary"]["cases_total"] == 15


def test_evidence_run_manifest_retrieval(monkeypatch, tmp_path: Path) -> None:
    _make_run(tmp_path, "run-a", 1_700_000_000)
    monkeypatch.setenv("REMORA_EVIDENCE_ROOT", str(tmp_path))
    client = TestClient(console_app.app)

    response = client.get("/api/evidence/runs/run-a")

    assert response.status_code == 200
    assert response.json()["run_id"] == "run-a"

    assert client.get("/api/evidence/runs/run-missing").status_code == 404


def test_evidence_run_archive_download(monkeypatch, tmp_path: Path) -> None:
    _make_run(tmp_path, "run-a", 1_700_000_000)
    monkeypatch.setenv("REMORA_EVIDENCE_ROOT", str(tmp_path))
    client = TestClient(console_app.app)

    response = client.get("/api/evidence/runs/run-a/archive")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "run-a" in response.headers.get("content-disposition", "")
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert "manifest.json" in archive.namelist()
    inner = json.loads(archive.read("manifest.json"))
    assert inner["run_id"] == "run-a"


def test_evidence_run_rejects_traversal_ids(monkeypatch, tmp_path: Path) -> None:
    _make_run(tmp_path, "run-a", 1_700_000_000)
    (tmp_path.parent / "outside.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setenv("REMORA_EVIDENCE_ROOT", str(tmp_path))
    client = TestClient(console_app.app)

    for bad in ("..", "..%2F..", "run%2Fa", ".hidden", "a" * 80):
        response = client.get(f"/api/evidence/runs/{bad}")
        assert response.status_code in (400, 404), bad
