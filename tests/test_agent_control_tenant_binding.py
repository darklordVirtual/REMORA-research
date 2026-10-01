# SPDX-License-Identifier: BUSL-1.1
"""Agent-control's administrative reads are bound to the deployment's tenant.

``/envelopes`` and ``/envelopes/verify`` used to take ``tenant_id`` from the
query string, so a holder of CONTROL_SECRET could read or verify any tenant's
chain in a shared D1 database, and ``/envelopes/<request_id>`` looked a row up
by request id alone. The tenant is now the deployment's ``TENANT_ID``; a
request naming another tenant is refused rather than silently redirected.

The resolver is a plain TypeScript module, executed here through node's type
stripping (node 22.18 and later). The route wiring is pinned against the
source, because the Worker itself needs the Workers runtime to run.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_WORKER = Path(__file__).resolve().parents[1] / "workers" / "agent-control"
_TENANT_TS = _WORKER / "src" / "tenant.ts"
_INDEX_TS = _WORKER / "src" / "index.ts"

_DRIVER = """
import { resolveReadTenant } from MODULE;
const cases = [
  [null, "acme"], ["acme", "acme"], ["other", "acme"], ["", "acme"],
  [null, undefined], ["default", undefined], ["acme", undefined],
];
console.log(JSON.stringify(cases.map(([req, conf]) => resolveReadTenant(req, conf))));
"""


@pytest.fixture(scope="module")
def resolutions(tmp_path_factory: pytest.TempPathFactory) -> list[dict]:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    driver = tmp_path_factory.mktemp("tenant") / "driver.mjs"
    driver.write_text(_DRIVER.replace("MODULE", json.dumps(_TENANT_TS.as_uri())),
                      encoding="utf-8")
    result = subprocess.run(["node", str(driver)], capture_output=True, text=True)
    if result.returncode != 0 and "Unknown file extension" in result.stderr:
        pytest.skip("this node cannot strip TypeScript types")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_no_tenant_requested_reads_the_configured_tenant(resolutions):
    assert resolutions[0] == {"ok": True, "tenant": "acme"}
    assert resolutions[3] == {"ok": True, "tenant": "acme"}


def test_naming_the_configured_tenant_is_allowed(resolutions):
    assert resolutions[1] == {"ok": True, "tenant": "acme"}


def test_naming_another_tenant_is_refused(resolutions):
    assert resolutions[2] == {"ok": False, "status": 403, "reason": "tenant_mismatch"}


def test_an_unconfigured_deployment_is_the_default_tenant_only(resolutions):
    assert resolutions[4] == {"ok": True, "tenant": "default"}
    assert resolutions[5] == {"ok": True, "tenant": "default"}
    assert resolutions[6] == {"ok": False, "status": 403, "reason": "tenant_mismatch"}


def _handler(name: str) -> str:
    source = _INDEX_TS.read_text(encoding="utf-8")
    start = source.index(f"async function {name}(")
    end = source.index("\nasync function ", start + 1)
    return source[start:end]


def test_no_handler_reads_the_tenant_from_the_query_as_authority():
    source = _INDEX_TS.read_text(encoding="utf-8")
    assert not re.search(r'searchParams\.get\("tenant_id"\)\s*\?\?', source), (
        "a query-string tenant must never override the deployment's tenant")


@pytest.mark.parametrize("name", ["handleEnvelopeList", "handleEnvelopeVerify",
                                  "handleAudit"])
def test_admin_reads_resolve_the_tenant(name):
    assert "resolveReadTenant(" in _handler(name)


def test_single_envelope_lookup_is_tenant_scoped():
    body = _handler("handleEnvelopeGet")
    assert "WHERE request_id = ? AND tenant_id = ?" in body
    assert "resolveReadTenant(" in body
