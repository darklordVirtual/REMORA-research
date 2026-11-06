# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's plant as its own trust domain: journal, credentials, topology (AACP E).

``deploy/ot-pilot/plant_service.py`` holds the plant's state behind two
credentials, and journals every request with the credential it presented.
These tests pin what the boundary run on the deployed stack relies on:

* the journal is complete for state changes: the state replayed from it
  equals the live state, and a change made outside ``Plant.apply`` breaks
  that equality, so the detector can see what it is meant to see;
* only the write credential changes state; the read credential, no
  credential and a wrong one are refused and journaled;
* ``ot_registry`` reaches the plant over HTTP with the write token, and
  refuses an in-process plant in production;
* ``reconcile`` reports an unattributed write, a dispatch the plant never
  saw and a journal that does not replay, each by itself;
* ``scripts/check_ot_pilot_topology.py`` passes on the committed files and
  fails on each drift it names.
"""
from __future__ import annotations

import copy
import importlib
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "deploy" / "ot-pilot"
sys.path.insert(0, str(PILOT))

import plant_model  # noqa: E402
import plant_service  # noqa: E402
import reconcile as reconcile_mod  # noqa: E402

WRITE = "w" * 40
READ = "r" * 40


# ── the model and its journal ──────────────────────────────────────────────

def test_every_applied_write_is_journaled_and_the_journal_replays_to_the_live_state():
    plant = plant_model.Plant()
    plant.apply("set_valve_position", {"valve": "V-12", "position_pct": 30},
                credential="writer", dispatch_ref="p1")
    plant.apply("adjust_setpoint", {"loop": "PIC-101", "value": 3.9}, credential="writer")
    plant.apply("create_work_order", {"wo_id": "WO-1310"}, credential="writer")
    applied = [e for e in plant.journal if e["outcome"] == "applied"]
    assert [e["tool"] for e in applied] == ["set_valve_position", "adjust_setpoint",
                                            "create_work_order"]
    assert applied[0]["dispatch_ref"] == "p1"
    assert applied[0]["rev_before"] == 0 and applied[0]["rev_after"] == 1
    assert plant.replay_digest() == plant.digest()


def test_a_change_outside_apply_breaks_the_replay():
    plant = plant_model.Plant()
    plant.apply("set_valve_position", {"valve": "V-12", "position_pct": 30}, credential="writer")
    plant.state["valves"]["V-18"]["pct"] = 99  # not through apply, not journaled
    assert plant.replay_digest() != plant.digest()


@pytest.mark.parametrize("credential", ["reader", "none", "invalid"])
def test_only_the_writer_changes_state_and_every_refusal_is_journaled(credential):
    plant = plant_model.Plant()
    before = plant.digest()
    with pytest.raises(plant_model.PlantRefused) as raised:
        plant.apply("set_valve_position", {"valve": "V-12", "position_pct": 30},
                    credential=credential)
    assert raised.value.status in (401, 403)
    assert plant.digest() == before
    assert plant.journal[-1]["outcome"] == "refused"
    assert plant.journal[-1]["credential"] == credential


def test_read_sensor_is_not_a_write_tool():
    plant = plant_model.Plant()
    with pytest.raises(plant_model.PlantRefused):
        plant.apply("read_sensor", {"sensor_id": "PT-101"}, credential="writer")


def test_declared_faults_are_journaled_with_the_write_and_still_replay():
    plant = plant_model.Plant(faults={"valve:V-12": ["clamp", 20], "loop:PIC-101": ["drop"],
                                      "alarm:LT-410-HI": ["hide"]})
    plant.apply("set_valve_position", {"valve": "V-12", "position_pct": 30}, credential="writer")
    plant.apply("adjust_setpoint", {"loop": "PIC-101", "value": 3.9}, credential="writer")
    plant.apply("acknowledge_alarm", {"alarm_id": "LT-410-HI"}, credential="writer")
    assert plant.state["valves"]["V-12"]["pct"] == 20
    assert plant.state["loops"]["PIC-101"]["setpoint"] == 4.0
    assert plant.revisions.get("loop:PIC-101", 0) == 0  # a dropped write changes nothing
    with pytest.raises(plant_model.PlantRefused):
        plant.read_object("alarm", "LT-410-HI")
    assert plant.journal[0]["fault"] == ["clamp", 20]
    assert plant.replay_digest() == plant.digest()


@pytest.mark.parametrize("bad", [{"valve:V-12": ["melt"]}, {"valve:V-12": ["clamp"]},
                                 {"valve:V-12": "drop"}, {"valve:V-12": ["clamp", True]}])
def test_a_malformed_fault_declaration_refuses_to_start(bad):
    with pytest.raises(ValueError):
        plant_model.Plant(faults=bad)


@pytest.mark.parametrize("value", [True, "4.2", None, [4.2]])
def test_a_setpoint_that_is_not_a_number_is_refused(value):
    plant = plant_model.Plant()
    with pytest.raises(plant_model.PlantRefused):
        plant.apply("adjust_setpoint", {"loop": "PIC-101", "value": value}, credential="writer")
    assert plant.state["loops"]["PIC-101"]["setpoint"] == 4.0


# ── the service over HTTP ──────────────────────────────────────────────────

@pytest.fixture()
def served():
    plant = plant_model.Plant()
    server = plant_service.build_server("127.0.0.1", 0, plant, {WRITE: "writer", READ: "reader"})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield plant, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _http(method, url, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method,
                                                           headers=headers), timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def test_the_service_needs_distinct_long_tokens(monkeypatch):
    monkeypatch.setenv("OT_PLANT_WRITE_TOKEN", "x" * 40)
    monkeypatch.setenv("OT_PLANT_READ_TOKEN", "x" * 40)
    with pytest.raises(SystemExit):
        plant_service._credentials()
    monkeypatch.setenv("OT_PLANT_READ_TOKEN", "short")
    with pytest.raises(SystemExit):
        plant_service._credentials()


@pytest.mark.parametrize("token", [None, "wrong" * 10, READ])
def test_over_http_only_the_write_token_writes(served, token):
    plant, url = served
    status, _ = _http("POST", f"{url}/tools/set_valve_position", token,
                      {"arguments": {"valve": "V-12", "position_pct": 30}})
    assert status in (401, 403)
    assert plant.state["valves"]["V-12"]["pct"] == 15
    assert plant.journal[-1]["outcome"] == "refused"


def test_over_http_the_writer_writes_and_the_reader_reads_it_back(served):
    plant, url = served
    status, body = _http("POST", f"{url}/tools/set_valve_position", WRITE,
                         {"arguments": {"valve": "V-12", "position_pct": 30},
                          "dispatch_ref": "pid-1"})
    assert status == 200 and body["new_pct"] == 30
    status, obj = _http("GET", f"{url}/objects/valve/V-12", READ)
    assert status == 200 and obj == {"kind": "valve", "id": "V-12", "pct": 30, "revision": 1}
    status, journal = _http("GET", f"{url}/journal", READ)
    applied = [e for e in journal["entries"] if e["outcome"] == "applied"]
    assert [e["dispatch_ref"] for e in applied] == ["pid-1"]
    status, digest = _http("GET", f"{url}/digest", READ)
    assert digest["live"] == digest["replayed"]


def test_over_http_a_read_without_a_credential_is_refused_and_journaled(served):
    plant, url = served
    assert _http("GET", f"{url}/journal")[0] == 401
    assert _http("GET", f"{url}/objects/valve/V-12", "nope" * 10)[0] == 401
    assert [e["credential"] for e in plant.journal] == ["none", "invalid"]


def test_over_http_an_unknown_route_is_refused_and_journaled(served):
    plant, url = served
    assert _http("POST", f"{url}/state", WRITE, {"x": 1})[0] == 404
    assert _http("PUT", f"{url}/tools/set_valve_position", WRITE, {})[0] == 405
    assert len(plant.journal) == 2 and plant.state == plant_model.INITIAL_STATE


# ── ot_registry against the service ────────────────────────────────────────

@pytest.fixture()
def remote_registry(served, monkeypatch):
    plant, url = served
    monkeypatch.setenv("OT_PLANT_URL", url)
    monkeypatch.setenv("OT_PLANT_WRITE_TOKEN", WRITE)
    sys.modules.pop("ot_registry", None)
    registry = importlib.import_module("ot_registry")
    yield plant, registry
    sys.modules.pop("ot_registry", None)


def test_the_registry_writes_through_the_plant_service(remote_registry):
    plant, registry = remote_registry
    assert registry._LOCAL is None and registry.PLANT == {}
    assert registry.set_valve_position({"valve": "V-12", "position_pct": 31})["new_pct"] == 31
    assert plant.state["valves"]["V-12"]["pct"] == 31
    assert registry.observe_limit_value("ot-pilot", "valve_travel", "V-12") == 31.0
    assert registry.read_sensor({"sensor_id": "PT-101"})["value"] == 4.10
    op = {"tool": "set_valve_position", "at": plant.started_at}
    assert registry.check_limit_evidence("ot-pilot", op,
                                         "plant-log:set_valve_position:V-12")["executed"] is True


def test_the_registry_with_a_wrong_token_changes_nothing(remote_registry, monkeypatch):
    plant, registry = remote_registry
    monkeypatch.setenv("OT_PLANT_WRITE_TOKEN", "x" * 40)
    with pytest.raises(plant_model.PlantRefused):
        registry.set_valve_position({"valve": "V-12", "position_pct": 31})
    assert plant.state["valves"]["V-12"]["pct"] == 15


def test_an_unknown_object_is_the_tools_own_value_error(remote_registry):
    _, registry = remote_registry
    with pytest.raises(ValueError):
        registry.adjust_setpoint({"loop": "PIC-999", "value": 1.0})


def test_an_unreachable_plant_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setenv("OT_PLANT_URL", "http://127.0.0.1:9")
    sys.modules.pop("ot_registry", None)
    registry = importlib.import_module("ot_registry")
    try:
        with pytest.raises(registry.PlantUnavailable):
            registry.set_valve_position({"valve": "V-12", "position_pct": 31})
    finally:
        sys.modules.pop("ot_registry", None)


def test_production_refuses_an_in_process_plant():
    env = {k: v for k, v in os.environ.items() if k != "OT_PLANT_URL"}
    env["REMORA_ENV"] = "production"
    done = subprocess.run([sys.executable, "-c", "import ot_registry"], cwd=PILOT, env=env,
                          capture_output=True, text=True, check=False)
    assert done.returncode != 0
    assert "refuses an in-process plant in production" in done.stderr


# ── reconciliation ─────────────────────────────────────────────────────────

def _journal(*refs):
    return [{"seq": i + 1, "tool": "set_valve_position", "outcome": "applied",
             "arguments": {"valve": "V-12"}, "dispatch_ref": ref} for i, ref in enumerate(refs)]


def _dispatch(pid, executed=True, tool="set_valve_position"):
    return {"proposal_id": pid, "executed": executed, "tool_name": tool}


def test_the_records_agree_when_every_write_is_a_dispatch_and_back():
    rec = reconcile_mod.reconcile(_journal("a", "b"), [_dispatch("a"), _dispatch("b"),
                                                       _dispatch("r", tool="read_sensor")],
                                  live_digest="d", replayed_digest="d")
    assert rec["agree"] is True and rec["applied_writes"] == 2


def test_an_unattributed_write_is_a_bypass():
    rec = reconcile_mod.reconcile(_journal("a", ""), [_dispatch("a")],
                                  live_digest="d", replayed_digest="d")
    assert rec["agree"] is False and len(rec["unattributed_writes"]) == 1


def test_a_write_naming_a_dispatch_that_did_not_execute_is_unattributed():
    rec = reconcile_mod.reconcile(_journal("a"), [_dispatch("a", executed=False)],
                                  live_digest="d", replayed_digest="d")
    assert rec["unattributed_writes"] and not rec["agree"]


def test_a_dispatch_the_plant_never_saw_and_a_dispatch_seen_twice_are_reported():
    rec = reconcile_mod.reconcile(_journal("a", "a"), [_dispatch("a"), _dispatch("b")],
                                  live_digest="d", replayed_digest="d")
    assert rec["dispatches_without_plant_record"] == ["b"]
    assert rec["dispatches_named_twice"] == ["a"]


def test_a_journal_that_does_not_replay_never_agrees():
    rec = reconcile_mod.reconcile(_journal("a"), [_dispatch("a")],
                                  live_digest="d1", replayed_digest="d2")
    assert rec["journal_complete"] is False and rec["agree"] is False


def test_the_interval_starts_after_the_mark():
    rec = reconcile_mod.reconcile(_journal("", "a"), [_dispatch("a")],
                                  live_digest="d", replayed_digest="d", since_seq=1)
    assert rec["agree"] is True


# ── the topology check ─────────────────────────────────────────────────────

def _checker(tmp_path, monkeypatch, *, register=None, compose=None):
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_ot_pilot_topology as checker

    import yaml

    reg = yaml.safe_load((PILOT / "credential_topology.yaml").read_text())
    comp = yaml.safe_load((PILOT / "docker-compose.yml").read_text())
    if register:
        register(reg)
    if compose:
        compose(comp)
    (tmp_path / "reg.yaml").write_text(yaml.safe_dump(reg))
    (tmp_path / "compose.yml").write_text(yaml.safe_dump(comp))
    monkeypatch.setattr(checker, "REGISTER", tmp_path / "reg.yaml")
    monkeypatch.setattr(checker, "COMPOSE", tmp_path / "compose.yml")
    monkeypatch.setattr(checker.Path, "relative_to", lambda self, other: self, raising=False)
    problems, _ = checker.check()
    return problems


def test_the_committed_topology_passes():
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_ot_pilot_topology.py")],
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def _env(comp, service):
    return comp["services"][service].setdefault("environment", {})


@pytest.mark.parametrize("name,mutate,expect", [
    ("agent carries the plant write token",
     lambda c: _env(c, "agent").__setitem__("OT_PLANT_WRITE_TOKEN", "${OT_PLANT_WRITE_TOKEN}"),
     "declared unreachable and the agent service carries it"),
    ("agent joins plant-net",
     lambda c: c["services"]["agent"]["networks"].append("plant-net"),
     "agent zone networks"),
    ("plant-net made non-internal",
     lambda c: c["networks"].__setitem__("plant-net", {}),
     "internal flag differs"),
    ("a new undeclared secret",
     lambda c: _env(c, "api").__setitem__("REMORA_NEW_TOKEN", "${OT_NEW_TOKEN}"),
     "undeclared credential OT_NEW_TOKEN"),
    ("a credential handed to one more service",
     lambda c: _env(c, "console").__setitem__("X", "${OT_PLANT_READ_TOKEN}"),
     "OT_PLANT_READ_TOKEN: holders"),
    ("a credential nobody carries any more",
     lambda c: _env(c, "verifier").pop("OT_VERIFIER_SIGNING_SEED"),
     "stale entry OT_VERIFIER_SIGNING_SEED"),
    ("postgres moved onto agent-net",
     lambda c: c["services"]["postgres"]["networks"].append("agent-net"),
     "agent network agent-net is shared with protected"),
])
def test_each_drift_fails_the_check(tmp_path, monkeypatch, name, mutate, expect):
    problems = _checker(tmp_path, monkeypatch, compose=mutate)
    assert any(expect in p for p in problems), (name, problems)


def test_a_reader_the_register_does_not_list_fails_the_check(tmp_path, monkeypatch):
    def drop_reader(reg):
        entry = next(e for e in reg["credentials"] if e["name"] == "OT_PLANT_WRITE_TOKEN")
        entry["read_by"] = ["deploy/ot-pilot/plant_service.py"]
    problems = _checker(tmp_path, monkeypatch, register=drop_reader)
    assert any("OT_PLANT_WRITE_TOKEN: read_by" in p for p in problems)


def test_initial_state_is_not_shared_between_plants():
    a, b = plant_model.Plant(), plant_model.Plant()
    a.apply("set_valve_position", {"valve": "V-12", "position_pct": 30}, credential="writer")
    assert b.state["valves"]["V-12"]["pct"] == 15
    assert plant_model.INITIAL_STATE == copy.deepcopy(plant_model.INITIAL_STATE)
    assert plant_model.INITIAL_STATE["valves"]["V-12"]["pct"] == 15


# ── adversarial review 2026-11-06 ──────────────────────────────────────────

def test_every_answered_request_is_journaled_reads_included(served):
    plant, url = served
    _http("GET", f"{url}/objects/valve/V-12", READ)
    _http("GET", f"{url}/objects/valve/V-99", READ)
    _http("GET", f"{url}/journal", READ)
    assert [(e["outcome"], e["credential"]) for e in plant.journal] == [
        ("read", "reader"), ("refused", "reader"), ("read", "reader")]


def test_an_object_reads_back_at_the_revision_a_write_produced():
    plant = plant_model.Plant()
    for pct in (30, 35):
        plant.apply("set_valve_position", {"valve": "V-12", "position_pct": pct},
                    credential="writer")
    assert plant.read_object("valve", "V-12")["pct"] == 35
    assert plant.read_object("valve", "V-12", 1) == {"kind": "valve", "id": "V-12",
                                                     "pct": 30, "revision": 1}
    assert plant.read_object("valve", "V-12", 0)["pct"] == 15
    for missing in (3, 7):
        with pytest.raises(plant_model.PlantRefused):
            plant.read_object("valve", "V-12", missing)


def test_health_reports_active_faults(monkeypatch):
    plant = plant_model.Plant(faults={"valve:V-12": ["clamp", 20]})
    server = plant_service.build_server("127.0.0.1", 0, plant, {WRITE: "writer", READ: "reader"})
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = _http("GET", f"http://127.0.0.1:{server.server_address[1]}/health")
        assert status == 200 and body["faults"] == {"valve:V-12": ["clamp", 20]}
    finally:
        server.shutdown()


@pytest.mark.parametrize("resource", ["V-12?dispatch_ref=x", "../tools/set_valve_position",
                                      "http://plant:9100/tools/x", "V-12/../../journal", "",
                                      "V 12", "V-12%2F..", None])
def test_the_limit_observer_never_sends_an_agent_string_to_the_plant(remote_registry, resource):
    plant, registry = remote_registry
    before = len(plant.journal)
    with pytest.raises(KeyError):
        registry.observe_limit_value("ot-pilot", "valve_travel", resource)
    assert len(plant.journal) == before  # no request reached the plant


def test_a_write_reusing_a_pre_window_reference_is_reported():
    rec = reconcile_mod.reconcile(_journal("a", "a"), [_dispatch("a")],
                                  live_digest="d", replayed_digest="d", since_seq=1)
    assert rec["dispatches_named_twice"] == ["a"] and rec["agree"] is False


def test_dispatches_before_the_window_are_not_missing():
    rec = reconcile_mod.reconcile(_journal("a", ""), [_dispatch("a")],
                                  live_digest="d", replayed_digest="d", since_seq=1)
    assert rec["dispatches_without_plant_record"] == []
    assert len(rec["unattributed_writes"]) == 1


def test_a_write_naming_a_dispatch_of_another_tool_is_a_mismatch():
    rec = reconcile_mod.reconcile(_journal("a"), [_dispatch("a", tool="adjust_setpoint")],
                                  live_digest="d", replayed_digest="d")
    assert rec["tool_mismatches"] and rec["agree"] is False


def test_an_unknown_outcome_accounts_for_its_write_and_is_never_missing():
    unknown = {"proposal_id": "a", "executed": False, "state_unknown": True,
               "tool_name": "set_valve_position"}
    assert reconcile_mod.reconcile(_journal("a"), [unknown], live_digest="d",
                                   replayed_digest="d")["agree"] is True
    assert reconcile_mod.reconcile([], [unknown], live_digest="d",
                                   replayed_digest="d")["agree"] is True


@pytest.mark.parametrize("name,mutate,expect", [
    ("agent gets an env_file",
     lambda c: c["services"]["agent"].__setitem__("env_file", [".env"]), "env_file"),
    ("agent mounts the deployment directory",
     lambda c: c["services"]["agent"].setdefault("volumes", []).append(".:/deploy"),
     "agent zone mounts"),
    ("agent is privileged",
     lambda c: c["services"]["agent"].__setitem__("privileged", True), "sets privileged"),
    ("agent shares the API's network namespace",
     lambda c: c["services"]["agent"].__setitem__("network_mode", "service:api"),
     "sets network_mode"),
    ("agent gets an undeclared key",
     lambda c: c["services"]["agent"].__setitem__("extra_hosts", ["plant:172.18.0.2"]),
     "undeclared keys"),
])
def test_ways_to_widen_the_agent_zone_fail_the_check(tmp_path, monkeypatch, name, mutate, expect):
    problems = _checker(tmp_path, monkeypatch, compose=mutate)
    assert any(expect in p for p in problems), (name, problems)
