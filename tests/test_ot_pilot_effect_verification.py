# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's effect verification through the real routes (AACP G).

The pilot's API runs in-process with its signed ToolSpec (schema 5, a
postcondition per write), the plant runs as ``plant_service`` on loopback
over the same in-process plant the registry writes to, and the effect
verifier is ``effect_verifier.Verifier`` with the plant's read-only token and
an Ed25519 receipt key the API registers for another control domain. Nothing
is mocked between the verifier's read-back and REMORA's verdict.

Pinned here, and on the deployed stack by ``run_effect_verification.py``:

* an honest write verifies, with vantage ``independent``;
* a clamped write is EFFECT_MISMATCH; a write acknowledged and never applied
  is EFFECT_MISMATCH ``postcondition_effect_absent``; an object the verifier
  cannot read is EFFECT_UNOBSERVABLE and never VERIFIED;
* a dispatch the plant has no record of is reported as an anomaly, not
  verified;
* the dispatch listing names every executed dispatch and its verdict.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

from tests.limits import test_limits_ot_pilot as _limits  # noqa: E402
from tests.limits.test_limits_ot_pilot import payload  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "deploy" / "ot-pilot"
SEED = "5c" * 32
READ = "r" * 40

pilot = _limits.pilot

import servers.api as _api  # noqa: E402

#: The real RBAC check, captured before the pilot fixture replaces it.
_REAL_CAPABILITY_CHECK = _api._require_tenant_capability


class ClientHttp:
    """effect_verifier.Http's interface over the in-process TestClient."""

    def __init__(self, client) -> None:
        self.client = client

    def call(self, method, path, body=None):
        r = self.client.request(method, path, json=body)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None


@pytest.fixture()
def stack(pilot, monkeypatch, tmp_path):
    from remora.crypto import SigningKey
    from remora.governance.effect_receipt_signing import RECEIPT_DOMAIN
    from remora.toolcall.toolspec_sign import sign_with_seed

    client = pilot()
    sys.path.insert(0, str(PILOT))
    import build_toolspec
    import effect_verifier
    import ot_registry
    import plant_service

    bundle, public, digest = sign_with_seed(build_toolspec.unsigned_bundle(), SEED,
                                            signed_at="2026-11-06T00:00:00+00:00")
    path = tmp_path / "toolspec-bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    key = SigningKey.generate({RECEIPT_DOMAIN})
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(path))
    monkeypatch.setenv("REMORA_TOOLSPEC_VERIFY_KEYS", public)
    monkeypatch.setenv("REMORA_TOOLSPEC_PINNED_DIGEST", digest)
    monkeypatch.delenv("REMORA_TOOLSPEC_SIGNING_KEY", raising=False)
    monkeypatch.setenv("REMORA_EXECUTOR_CONTROL_DOMAIN", "ot-pilot-executor")
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_KEYS", json.dumps([{
        "public_key": key.verification_key().public_bytes.hex(),
        "control_domain": "ot-pilot-plant-observer", "credential_scope": "read_only",
        "tenants": ["ot-pilot"]}]))
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: ("ot-effect-verifier" if "/effect" in request.url.path
                                         else "ot-agent"))
    exec_mod._reset_toolspec_bundle()
    exec_mod._reset_tool_dispatcher()

    server = plant_service.build_server("127.0.0.1", 0, ot_registry._LOCAL,
                                        {"w" * 40: "writer", READ: "reader"})
    threading.Thread(target=server.serve_forever, daemon=True).start()
    verifier = effect_verifier.Verifier(
        ClientHttp(client),
        effect_verifier.Http(f"http://127.0.0.1:{server.server_address[1]}", READ), key)
    yield client, ot_registry, verifier
    server.shutdown()


def _write(client, tool, intent, **arguments):
    p = payload(tool, intent, **arguments)
    assessed = client.post("/v1/execution/assess", json=p).json()
    item = assessed["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item, "approval_ttl_seconds": 900}).status_code == 200
    executed = client.post("/v1/execution/execute", json={"item_id": item, "tool_call": p}).json()
    assert executed["outcome"] == "execute", executed
    return assessed["proposal_id"]


def _effect(client, pid):
    return client.get(f"/v1/execution/proposals/{pid}").json()["effect"]


def test_an_honest_write_verifies_independently_from_the_plant_read_back(stack):
    client, registry, verifier = stack
    pid = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    assert registry._LOCAL.journal[-1]["dispatch_ref"] == pid
    verifier.run_once()
    effect = _effect(client, pid)
    assert (effect["status"], effect["vantage"], effect["verdict_source"]) == (
        "EFFECT_VERIFIED", "independent", "computed")
    assert verifier.report()["reconciliation"]["agree"] is True


@pytest.mark.parametrize("tool,intent,args,fault,status,reason", [
    ("set_valve_position", "WO-1204", {"valve": "V-12", "position_pct": 30},
     ("valve:V-12", ("clamp", 20)), "EFFECT_MISMATCH", "postcondition_field_mismatch"),
    ("adjust_setpoint", "WO-1201", {"loop": "PIC-101", "value": 3.9},
     ("loop:PIC-101", ("drop", None)), "EFFECT_MISMATCH", "postcondition_effect_absent"),
    ("acknowledge_alarm", "WO-1202", {"alarm_id": "LT-410-HI"},
     ("alarm:LT-410-HI", ("hide", None)), "EFFECT_UNOBSERVABLE", "postcondition_object_absent"),
])
def test_a_faulty_plant_is_never_verified(stack, tool, intent, args, fault, status, reason):
    client, registry, verifier = stack
    registry._LOCAL.faults[fault[0]] = fault[1]
    pid = _write(client, tool, intent, **args)
    for _ in range(3):
        verifier.run_once()
    effect = _effect(client, pid)
    assert (effect["status"], effect["reason_code"]) == (status, reason)
    assert all(h["status"] != "EFFECT_VERIFIED" for h in effect["history"])


def test_every_write_tool_verifies_on_an_honest_plant(stack):
    client, _, verifier = stack
    pids = [
        _write(client, "adjust_setpoint", "WO-1201", loop="PIC-101", value=3.9),
        _write(client, "acknowledge_alarm", "WO-1202", alarm_id="LT-410-HI"),
        _write(client, "create_work_order", "WO-1205", wo_id="WO-1310"),
        _write(client, "close_work_order", "WO-1203", wo_id="WO-1201"),
    ]
    verifier.run_once()
    assert [_effect(client, p)["status"] for p in pids] == ["EFFECT_VERIFIED"] * 4


def test_a_dispatch_the_plant_has_no_record_of_is_an_anomaly_not_a_verdict(stack):
    client, registry, verifier = stack
    pid = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    registry._LOCAL.journal.pop()  # the plant "lost" the write
    rec = verifier.run_once()
    assert verifier.report()["anomalies"][0]["reason"] == "dispatch_without_plant_record"
    assert rec["dispatches_without_plant_record"] == [pid]
    assert _effect(client, pid)["status"] is None


def test_the_dispatch_listing_names_each_execution_and_its_verdict(stack):
    client, _, verifier = stack
    read = client.post("/v1/execution/assess",
                       json=payload("read_sensor", "MON-ROUND", sensor_id="PT-101")).json()
    pid = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    verifier.run_once()
    rows = client.get("/v1/execution/dispatches").json()["dispatches"]
    by_pid = {r["proposal_id"]: r for r in rows}
    assert by_pid[pid]["tool_name"] == "set_valve_position"
    assert by_pid[pid]["executed"] is True and by_pid[pid]["effect_status"] == "EFFECT_VERIFIED"
    assert len(by_pid[pid]["tool_call_hash"]) == 64
    assert read["proposal_id"] not in by_pid or by_pid[read["proposal_id"]]["tool_name"] == \
        "read_sensor"
    page = client.get(f"/v1/execution/dispatches?after_sequence={rows[-1]['sequence_no']}").json()
    assert page["dispatches"] == []


# ── adversarial review 2026-11-06 ──────────────────────────────────────────

def test_two_writes_before_a_pass_are_each_verified_against_their_own_revision(stack):
    """The second write must not stand in for the first (it used to be read as
    the first write's effect, a settled MISMATCH for a correct write)."""
    client, _, verifier = stack
    first = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    second = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=40)
    verifier.run_once()
    assert [_effect(client, p)["status"] for p in (first, second)] == ["EFFECT_VERIFIED"] * 2
    revisions = {r["proposal_id"]: r["source_revision"] for r in verifier.report()["results"]}
    assert (revisions[first], revisions[second]) == ("1", "2")


def test_a_dropped_write_is_not_verified_by_a_later_write_of_the_same_value(stack):
    client, registry, verifier = stack
    registry._LOCAL.faults["valve:V-12"] = ("drop", None)
    dropped = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    registry._LOCAL.faults.pop("valve:V-12")
    applied = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    verifier.run_once()
    assert (_effect(client, dropped)["status"], _effect(client, dropped)["reason_code"]) == (
        "EFFECT_MISMATCH", "postcondition_effect_absent")
    assert _effect(client, applied)["status"] == "EFFECT_VERIFIED"


@pytest.mark.parametrize("role,expected", [("operator", 403), ("viewer", 403),
                                           ("effect_verifier", 200), ("admin", 200)])
def test_the_dispatch_listing_needs_verify_effect(stack, monkeypatch, role, expected):
    client, _, _ = stack
    import servers.api as api_mod

    monkeypatch.setattr(api_mod, "_require_tenant_capability", _REAL_CAPABILITY_CHECK)
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("ot-pilot", role))
    assert client.get("/v1/execution/dispatches").status_code == expected


def test_a_negative_cursor_is_read_as_zero(stack):
    client, _, _ = stack
    body = client.get("/v1/execution/dispatches?after_sequence=-5").json()
    assert body["next_after_sequence"] >= 0


# ── a writer that is not REMORA's executor (NEGATIVE_RESULTS §85, 2026-11-10) ──

OTHER_WRITER = "o" * 40


def _post_to_plant(verifier, token, tool, arguments, dispatch_ref=""):
    """A write straight to the plant service with *token*, as another system would make it."""
    import effect_verifier

    return effect_verifier.Http(verifier.plant.base, token).call(
        "POST", f"/tools/{tool}", {"arguments": arguments, "dispatch_ref": dispatch_ref})


@pytest.fixture()
def two_writers(stack):
    """The stack, with a second writer credential at the plant and a verifier
    that knows which credential is the executor's."""
    import plant_service

    client, registry, verifier = stack
    server = plant_service.build_server(
        "127.0.0.1", 0, registry._LOCAL,
        {"w" * 40: "writer", OTHER_WRITER: "writer", READ: "reader"})
    threading.Thread(target=server.serve_forever, daemon=True).start()
    verifier.plant.base = f"http://127.0.0.1:{server.server_address[1]}"
    yield client, registry, verifier
    server.shutdown()


def test_a_dropped_write_is_not_verified_by_another_writers_write_of_the_same_value(two_writers):
    """The other writer does not name REMORA's dispatch. Revisions already
    separate the two: REMORA's write changed nothing, and the report lists
    the plant write no dispatch accounts for."""
    client, registry, verifier = two_writers
    registry._LOCAL.faults["valve:V-12"] = ("drop", None)
    dropped = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    registry._LOCAL.faults.pop("valve:V-12")
    status, _ = _post_to_plant(verifier, OTHER_WRITER, "set_valve_position",
                               {"valve": "V-12", "position_pct": 30})
    assert status == 200
    rec = verifier.run_once()
    effect = _effect(client, dropped)
    assert (effect["status"], effect["reason_code"]) == (
        "EFFECT_MISMATCH", "postcondition_effect_absent")
    (unattributed,) = rec["unattributed_writes"]
    assert unattributed["tool"] == "set_valve_position"


def test_the_journal_records_which_credential_wrote_without_recording_the_credential(two_writers):
    import plant_service

    client, registry, verifier = two_writers
    _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    _post_to_plant(verifier, OTHER_WRITER, "set_valve_position",
                   {"valve": "V-12", "position_pct": 35})
    mine, theirs = registry._LOCAL.journal[-2:]
    assert mine["credential_id"] == "in-process"
    assert theirs["credential_id"] == plant_service.credential_id(OTHER_WRITER)
    assert theirs["credential"] == "writer" and OTHER_WRITER not in json.dumps(theirs)
    assert plant_service.credential_id(OTHER_WRITER) != plant_service.credential_id("w" * 40)


def test_another_writer_that_names_remoras_dispatch_is_an_anomaly_when_the_executor_is_known(
        two_writers):
    """REMORA's own write never reached the plant. Another holder of a write
    credential makes the same write and puts REMORA's dispatch reference on
    it. A verifier told which credential is the executor's does not verify it."""
    client, registry, verifier = two_writers
    verifier.expected_writer_id = "in-process"
    pid = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    registry._LOCAL.journal.pop()  # the executor's write is not in the plant's record
    status, _ = _post_to_plant(verifier, OTHER_WRITER, "set_valve_position",
                               {"valve": "V-12", "position_pct": 30}, dispatch_ref=pid)
    assert status == 200
    verifier.run_once()
    assert _effect(client, pid)["status"] is None
    (anomaly,) = verifier.report()["anomalies"]
    assert anomaly["reason"] == "plant_write_by_another_credential"
    assert anomaly["proposal_id"] == pid and anomaly["expected_writer_id"] == "in-process"
    # It stays an anomaly: later passes do not turn it into a verdict.
    for _ in range(6):
        verifier.run_once()
    assert _effect(client, pid)["status"] is None


def test_limit_without_a_known_executor_credential_the_forged_reference_is_verified(two_writers):
    """The open half of §85: the pilot's verifier is not told which credential
    is the executor's, and the plant has one write token. Whoever holds a
    write credential can then have its write verified as REMORA's dispatch."""
    client, registry, verifier = two_writers
    assert verifier.expected_writer_id is None
    pid = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    registry._LOCAL.journal.pop()
    _post_to_plant(verifier, OTHER_WRITER, "set_valve_position",
                   {"valve": "V-12", "position_pct": 30}, dispatch_ref=pid)
    verifier.run_once()
    assert _effect(client, pid)["status"] == "EFFECT_VERIFIED"


def test_the_executors_own_write_still_verifies_when_the_executor_is_known(two_writers):
    client, _, verifier = two_writers
    verifier.expected_writer_id = "in-process"
    pid = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    verifier.run_once()
    assert _effect(client, pid)["status"] == "EFFECT_VERIFIED"
    assert verifier.report()["anomalies"] == []


# ── after review ───────────────────────────────────────────────────────────

def test_a_journal_entry_without_a_credential_id_is_its_own_anomaly(two_writers):
    """An older plant, or one that does not report who wrote: not verified,
    and not blamed on another writer."""
    client, registry, verifier = two_writers
    verifier.expected_writer_id = "in-process"
    pid = _write(client, "set_valve_position", "WO-1204", valve="V-12", position_pct=30)
    registry._LOCAL.journal[-1].pop("credential_id")
    verifier.run_once()
    (anomaly,) = verifier.report()["anomalies"]
    assert anomaly["reason"] == "plant_write_without_credential_id"
    assert _effect(client, pid)["status"] is None


def test_a_kept_connection_does_not_carry_a_credential_id_into_the_next_request(two_writers):
    """With keep-alive, one handler serves several requests. A refused request
    after a good one must be journaled without the good one's credential id."""
    import http.client
    import urllib.parse

    import plant_service

    _client, registry, verifier = two_writers
    host = urllib.parse.urlsplit(verifier.plant.base)
    plant_service.PlantHandler.protocol_version = "HTTP/1.1"
    try:
        conn = http.client.HTTPConnection(host.hostname, host.port, timeout=5)
        body = json.dumps({"arguments": {"valve": "V-12", "position_pct": 31}})
        for token in (OTHER_WRITER, "x" * 40, None):
            headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            conn.request("POST", "/tools/set_valve_position", body=body, headers=headers)
            conn.getresponse().read()
        conn.close()
    finally:
        plant_service.PlantHandler.protocol_version = "HTTP/1.0"
    good, invalid, none = registry._LOCAL.journal[-3:]
    assert good["credential_id"] == plant_service.credential_id(OTHER_WRITER)
    assert (invalid["credential"], none["credential"]) == ("invalid", "none")
    assert invalid.get("credential_id", "") == "" and none.get("credential_id", "") == ""


def test_the_pilot_compose_file_does_not_tell_the_verifier_which_credential_is_the_executors():
    """What NEGATIVE_RESULTS §85 (2026-11-10) records as the open half. When the
    pilot sets it, this fails and §85 is updated."""
    compose = (PILOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "OT_EXECUTOR_WRITER_ID" not in compose


def test_the_writer_id_a_verifier_needs_can_be_printed_without_the_token(monkeypatch, capsys):
    import plant_service

    monkeypatch.setenv("OT_PLANT_WRITE_TOKEN", "w" * 40)
    monkeypatch.setenv("OT_PLANT_READ_TOKEN", "r" * 40)
    monkeypatch.setattr("sys.argv", ["plant_service.py", "--writer-id"])
    plant_service.main()
    out = capsys.readouterr().out.strip()
    assert out == plant_service.credential_id("w" * 40) and "w" * 40 not in out
