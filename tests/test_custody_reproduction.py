# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Public reproduction must observe real process dispatch and durable refusal."""
import json
from pathlib import Path

from scripts.reproduce_custody import evaluate


def test_separate_process_custody_and_restart_controls(tmp_path: Path) -> None:
    result = evaluate(tmp_path)
    cases = result["cases"]
    assert cases["valid"]["executed"] is True
    assert cases["valid"]["effect_count"] == 1
    assert cases["restart_replay"]["executed"] is False
    assert cases["restart_replay"]["refusal_reason"] == "nonce_already_consumed"
    assert cases["restart_replay"]["effect_count"] == 1
    for name in ("wrong_call", "wrong_tenant", "wrong_principal", "wrong_runtime", "expired", "tampered", "self_mint"):
        assert cases[name]["executed"] is False, name
        assert cases[name]["effect_count"] == 0, name
    for name in ("authority_holds_credential", "executor_holds_signing_key", "undeclared_inventory"):
        assert cases[name]["custody_refused"] is True, name
    assert result["authority_pid"] != cases["valid"]["pid"]
    assert cases["lost_response"]["state_unknown"] is True
    assert cases["lost_response_restart"]["effect_count"] == 1
    assert cases["lost_response_restart"]["refusal_reason"] == "nonce_already_consumed"
    assert sum(row["executed"] for row in cases["concurrent"]["attempts"]) == 1
    assert cases["concurrent"]["effect_count"] == 1
    assert result["claim_boundary"]["host_isolation"] == "NOT_ESTABLISHED"
    serialized = json.dumps(result)
    assert "PRIVATE" not in serialized
    assert "synthetic-custody-credential" not in serialized
