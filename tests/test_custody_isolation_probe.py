# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The custody isolation probe's verdict logic and its committed result (AACP E-01)."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "artifacts" / "assurance" / "custody-isolation-probe-2026-11-10" / "result.json"


def _module():
    spec = importlib.util.spec_from_file_location(
        "probe_custody_isolation", ROOT / "scripts" / "probe_custody_isolation.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _layouts():
    return copy.deepcopy(json.loads(RESULT.read_text(encoding="utf-8"))["layouts"])


def _row(layouts, name):
    return next(row for row in layouts if row["layout"] == name)


def test_committed_result_shows_the_split_and_the_leaking_control():
    m = _module()
    d = json.loads(RESULT.read_text(encoding="utf-8"))
    assert d["schema"] == "remora-custody-isolation-probe/v1" and d["isolation_shown"] is True
    assert m.verdict(d["layouts"])["checks"] == d["checks"] and all(d["checks"].values())
    assert d["container"]["network"] == "none"
    control, split = _row(d["layouts"], "same_user"), _row(d["layouts"], "os_user")
    leaked = {a["technique"] for a in control["attempts"] if a["read_credential"]}
    assert leaked == {"proc_environ", "proc_mem"}
    assert split["profile"] == "controlled_pilot" and split["holder_uid"] != split["agent_uid"]
    assert {a["technique"]: a["error"] for a in split["attempts"]} == {
        "proc_environ": "PermissionError", "proc_mem": "PermissionError",
        "proc_cmdline": None, "proc_fd": "PermissionError", "proc_cwd": "PermissionError",
        "signal_0": "PermissionError"}
    assert [a["technique"] for a in split["attempts"]] == list(m.TECHNIQUES)
    # No run's credential is stored.
    assert "probe-" not in RESULT.read_text(encoding="utf-8")


def test_a_control_that_does_not_leak_shows_nothing():
    m = _module()
    layouts = _layouts()
    for attempt in _row(layouts, "same_user")["attempts"]:
        attempt["read_credential"] = False
    _row(layouts, "same_user")["credential_read"] = False
    out = m.verdict(layouts)
    assert out["checks"]["control_leaks"] is False and out["isolation_shown"] is False


def test_a_split_that_leaks_or_never_started_is_not_isolation():
    m = _module()
    leaking = _layouts()
    _row(leaking, "os_user")["credential_read"] = True
    assert m.verdict(leaking)["isolation_shown"] is False
    refused = _layouts()
    _row(refused, "os_user").update(holder_started=False, guard="REFUSED something else")
    out = m.verdict(refused)
    assert out["checks"]["split_starts_under_strict_profile"] is False
    assert out["checks"]["split_reads_nothing"] is False


def test_a_refusal_for_another_rule_is_not_counted_as_the_isolation_check():
    m = _module()
    layouts = _layouts()
    _row(layouts, "os_user_declared_but_shared")["guard"] = (
        "REFUSED custody split violated for role 'executor': the execution domain must hold "
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC")
    assert m.verdict(layouts)["checks"]["shared_uid_refused_by_guard"] is False
    started = _layouts()
    _row(started, "os_user_as_root").update(holder_started=True, guard="READY executor")
    assert m.verdict(started)["checks"]["root_holder_refused_by_guard"] is False


def test_the_agent_must_have_run_as_the_agent_uid():
    m = _module()
    layouts = _layouts()
    _row(layouts, "os_user")["agent_ran_as"] = 0
    assert m.verdict(layouts)["isolation_shown"] is False


def test_the_pilot_compose_file_still_declares_no_profile_role_or_isolation():
    """What NEGATIVE_RESULTS §104 records. When the pilot gains a custody
    split this fails, and §104 and the probe's README are updated with it."""
    compose = (ROOT / "deploy" / "ot-pilot" / "docker-compose.yml").read_text(encoding="utf-8")
    for name in ("REMORA_RUNTIME_PROFILE", "REMORA_EXECUTION_DOMAIN_ROLE",
                 "REMORA_EXECUTION_ISOLATION"):
        assert name not in compose
