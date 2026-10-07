# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A forwarding authority builds no tool dispatcher.

Found while mapping the MCP execution surfaces (stage H, 2026-10-07). The
API's dispatch path evaluated ``_tool_dispatcher()`` before deciding whether
it would execute locally or forward the lease to the execution domain. Building
the dispatcher imports the registry and registers its callables, which the
custody guard refuses in the authority domain under a strict profile. Probe at
c8cc91d: with the scaffold's authority configuration and an execution endpoint
set, ``_tool_dispatcher()`` raises ``CustodyViolation``, so a strict authority
could not forward a single call.

``dispatch_under_lease`` already accepts no dispatcher when it forwards. The
API now passes one only when this process will execute locally.
"""
from __future__ import annotations

import shlex

import pytest

pytest.importorskip("cryptography")


@pytest.fixture
def authority(monkeypatch, tmp_path):
    from remora.scaffold import init_review

    monkeypatch.chdir(tmp_path)
    init_review(tmp_path / ".remora")
    for name in (
        "REMORA_TOOLSPEC_SIGNING_KEY",
        "REMORA_LEASE_SIGNING_KEY",
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC",
        "REMORA_PG_DSN",
        "REMORA_SIGNATURE_FORMAT",
    ):
        monkeypatch.delenv(name, raising=False)
    text = (tmp_path / ".remora" / "authority.env").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("export "):
            key, _, raw = line[len("export "):].partition("=")
            monkeypatch.setenv(key, shlex.split(raw)[0])
    monkeypatch.syspath_prepend(str(tmp_path / ".remora"))
    import servers.execution_api as exec_mod

    monkeypatch.setattr(exec_mod, "_BINDING_POLICY_CACHE", None)
    monkeypatch.setattr(exec_mod, "_current_policy_bundle_hash", lambda: "b1")
    exec_mod._reset_tool_dispatcher()
    yield exec_mod
    exec_mod._reset_tool_dispatcher()


def test_a_forwarding_authority_needs_no_tool_dispatcher(authority, monkeypatch) -> None:
    monkeypatch.setenv("REMORA_EXECUTION_ENDPOINT", "http://127.0.0.1:8011")
    assert authority._local_dispatcher(presented_lease=None) is None


def test_the_authority_still_may_not_hold_callables(authority, monkeypatch) -> None:
    """Executing locally in the authority is still refused, as before."""
    from remora.enforcement.custody import CustodyViolation

    monkeypatch.delenv("REMORA_EXECUTION_ENDPOINT", raising=False)
    with pytest.raises(CustodyViolation, match="authority domain must not register"):
        authority._local_dispatcher(presented_lease=None)


def test_a_presented_lease_is_executed_here_and_needs_the_dispatcher(authority,
                                                                     monkeypatch) -> None:
    """A lease that arrived is never forwarded again: it runs where it landed."""
    monkeypatch.setenv("REMORA_EXECUTION_ENDPOINT", "http://127.0.0.1:8011")
    sentinel = object()
    monkeypatch.setattr(authority, "_tool_dispatcher", lambda: sentinel)
    assert authority._local_dispatcher(presented_lease=object()) is sentinel
