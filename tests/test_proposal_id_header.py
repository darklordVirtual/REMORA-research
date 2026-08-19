# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Phase 13: X-Remora-Proposal-Id response-header correlation.

One stable proposal id must correlate ingress through effect verification.
The body and the audit chain already carry it (FT-01); these tests pin the
transport-layer surface: execution responses expose the same id as a
response header, and requests with no proposal involved carry no header.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from servers.api import app

AUTH = {"Authorization": "Bearer ot-agent"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_assess_response_header_matches_body(client: TestClient) -> None:
    resp = client.post(
        "/v1/execution/assess",
        json={"tool_name": "read_telemetry", "arguments": {"sensor": "PT-1"},
              "target_environment": "staging"},
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert resp.headers.get("X-Remora-Proposal-Id") == body["proposal_id"]


def test_lifecycle_read_carries_the_same_id(client: TestClient) -> None:
    assess = client.post(
        "/v1/execution/assess",
        json={"tool_name": "read_telemetry", "arguments": {"sensor": "PT-2"},
              "target_environment": "staging"},
        headers=AUTH,
    )
    pid = assess.json()["proposal_id"]
    lifecycle = client.get(f"/v1/execution/proposals/{pid}/lifecycle", headers=AUTH)
    assert lifecycle.headers.get("X-Remora-Proposal-Id") == pid


def test_non_proposal_requests_have_no_header(client: TestClient) -> None:
    resp = client.get("/v1/metrics", headers=AUTH)
    assert "X-Remora-Proposal-Id" not in resp.headers
