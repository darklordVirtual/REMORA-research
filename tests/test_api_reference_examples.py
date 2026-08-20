# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The documented API example is executed, not just proofread.

`docs/07-api-reference.md` says every signature in it is verified against
source by `tests/test_api_reference_doc.py`. That gate checks *signatures*.
The HTTP example added on 2026-08-20 was wrong in three independent ways and
shipped anyway: it named the response key `decision` (it is
`policy_decision`), it showed `action: escalate` (the server returns
`abstain`), and it quoted a reason string — `risk_tier_critical_floor` — that
is not a member of `DecisionReason` and therefore can never appear.

An integrator copies that block first. So this test runs the documented
request against the real app and asserts the response matches what the
document promises. Prose can be reviewed; only execution can be trusted.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "07-api-reference.md"

#: The request the document tells the reader to make.
_DOCUMENTED_REQUEST = {
    "question": "Restart the payments worker in production",
    "tool_call": {
        "tool_name": "restart_service",
        "arguments": {"service": "payments-worker", "environment": "prod"},
    },
}


@pytest.fixture
def dev_client(monkeypatch: pytest.MonkeyPatch):
    """A client under exactly the development profile the document documents."""
    for key, value in {
        "REMORA_ENV": "development",
        "REMORA_API_BEARER_TOKEN": "dev-token",
        "REMORA_ORACLE_BACKEND": "mock",
        "REMORA_API_ALLOW_MOCK_ORACLES": "true",
    }.items():
        monkeypatch.setenv(key, value)
    from fastapi.testclient import TestClient

    import servers.api as api

    return TestClient(api.app)


def _documented_response() -> dict:
    """The JSON block the document shows for the /v1/assess round trip."""
    text = DOC.read_text(encoding="utf-8")
    marker = text.index("The decision key is **`policy_decision`**")
    blocks = re.findall(r"```json\n(.*?)```", text[:marker], re.S)
    assert blocks, "no JSON response block found in the API reference"
    return json.loads(blocks[-1])


def test_the_documented_request_succeeds(dev_client) -> None:
    response = dev_client.post(
        "/v1/assess",
        headers={"Authorization": "Bearer dev-token"},
        json=_DOCUMENTED_REQUEST,
    )
    assert response.status_code == 200, response.text


def test_documented_keys_exist_in_the_real_response(dev_client) -> None:
    """Every key the document shows must be a key the server actually returns.

    Abridging is fine — inventing is not.
    """
    actual = dev_client.post(
        "/v1/assess",
        headers={"Authorization": "Bearer dev-token"},
        json=_DOCUMENTED_REQUEST,
    ).json()
    documented = _documented_response()

    missing = [k for k in documented if k not in actual]
    assert missing == [], f"documented top-level keys the API does not return: {missing}"

    for section in ("policy_decision",):
        doc_section = documented.get(section, {})
        real_section = actual.get(section, {})
        absent = [k for k in doc_section if k not in real_section]
        assert absent == [], f"documented {section} keys not returned: {absent}"

    doc_audit = documented.get("envelope", {}).get("audit", {})
    real_audit = actual.get("envelope", {}).get("audit", {})
    absent = [k for k in doc_audit if k not in real_audit]
    assert absent == [], f"documented audit keys not returned: {absent}"


def test_documented_decision_matches_the_real_one(dev_client) -> None:
    """The action and reasons shown are the ones this request produces."""
    actual = dev_client.post(
        "/v1/assess",
        headers={"Authorization": "Bearer dev-token"},
        json=_DOCUMENTED_REQUEST,
    ).json()["policy_decision"]
    documented = _documented_response()["policy_decision"]

    assert documented["action"] == actual["action"], (
        f"the document shows action={documented['action']!r} but the server "
        f"returns {actual['action']!r} for the documented request"
    )
    assert documented["reasons"] == actual["reasons"], (
        f"the document shows reasons={documented['reasons']} but the server "
        f"returns {actual['reasons']}"
    )


def test_every_documented_reason_is_a_real_decision_reason() -> None:
    """A reason string that cannot occur is worse than a missing example."""
    from remora.policy.report import DecisionReason

    valid = {r.value for r in DecisionReason}
    documented = _documented_response()["policy_decision"]["reasons"]
    unknown = [r for r in documented if r not in valid]
    assert unknown == [], (
        f"the document quotes reason strings that are not members of "
        f"DecisionReason and can never appear: {unknown}"
    )


def test_the_documented_action_is_one_of_the_four(dev_client) -> None:
    documented = _documented_response()["policy_decision"]["action"]
    assert documented in {"accept", "verify", "abstain", "escalate"}


def test_the_environment_the_document_sets_is_the_one_it_needs() -> None:
    """The env block above the curl example must name what the request needs."""
    text = DOC.read_text(encoding="utf-8")
    for var in ("REMORA_ENV", "REMORA_API_BEARER_TOKEN", "REMORA_ORACLE_BACKEND"):
        assert var in text, f"the documented setup omits {var}"
    assert os.environ.get("REMORA_ENV") != "production", (
        "this test must never run against a production configuration"
    )
