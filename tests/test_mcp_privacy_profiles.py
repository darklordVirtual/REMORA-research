# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Privacy-profile regression suite for servers/mcp_remora.py (Phase 9).

Pins the contract: the DEFAULT profile is 'local' and sends nothing off the
machine (proven with outbound network monkey-patched to fail if touched);
'demo' requires explicit opt-in and emits a disclosure; 'enterprise' requires
explicit endpoints and refuses startup when incomplete. No profile ever
silently substitutes another profile's endpoints.
"""
from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture()
def mcp(monkeypatch: pytest.MonkeyPatch):
    """Import a fresh mcp_remora with a clean (default) environment and the
    network monkey-patched to explode if anything touches it."""
    for var in (
        "REMORA_MCP_PROFILE", "REMORA_PROFILE", "REMORA_WORKER_URL",
        "RAG_WORKER_URL", "LAW_SEARCH_WORKER_URL", "AGENT_CONTROL_URL",
        "AGENT_CONTROL_SECRET", "CODEGRAPH_URL", "REPO_SEARCH_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    import socket
    import urllib.request

    def _no_network(*_a, **_k):  # pragma: no cover - must never run
        raise AssertionError("outbound network touched in default MCP profile")

    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)

    sys.modules.pop("servers.mcp_remora", None)
    module = importlib.import_module("servers.mcp_remora")
    yield module
    sys.modules.pop("servers.mcp_remora", None)


def test_default_profile_is_local(mcp) -> None:
    assert mcp.MCP_PROFILE == "local"


def test_default_profile_has_no_external_endpoints(mcp) -> None:
    assert mcp.REMORA_WORKER == ""
    assert mcp.RAG_WORKER == ""
    assert mcp.LAW_SEARCH_WORKER == ""
    assert mcp.AGENT_CONTROL == ""
    assert mcp.CODEGRAPH_URL == ""
    assert mcp.REPO_SEARCH_URL == ""


def test_default_profile_makes_zero_network_calls(mcp) -> None:
    # Import already succeeded under the network trap; remote helpers must
    # refuse without touching the (exploding) network.
    post = mcp._post(mcp.REMORA_WORKER + "/assess" if mcp.REMORA_WORKER else "", {"q": 1})
    get = mcp._get(mcp.LAW_SEARCH_WORKER)
    assert "error" in post and "local" in post["error"]
    assert "error" in get and "local" in get["error"]


def test_local_profile_ignores_inherited_endpoint_vars(mcp) -> None:
    profile, urls = mcp.resolve_profile(
        {
            "REMORA_MCP_PROFILE": "local",
            # Inherited variables must not become a silent data path.
            "REMORA_WORKER_URL": "https://somewhere.example",
            "AGENT_CONTROL_URL": "https://control.example",
        }
    )
    assert profile == "local"
    assert all(v == "" for v in urls.values())


def test_demo_requires_explicit_opt_in_and_discloses(mcp, capsys) -> None:
    profile, urls = mcp.resolve_profile({"REMORA_MCP_PROFILE": "demo"})
    captured = capsys.readouterr()
    assert profile == "demo"
    assert "razorsharp.workers.dev" in urls["remora"]
    assert "leaves" in captured.err  # disclosure emitted to stderr
    # No public demo control plane: write/agent surface stays disabled.
    assert urls["control_url"] == ""


def test_enterprise_complete_uses_exact_endpoints(mcp) -> None:
    profile, urls = mcp.resolve_profile(
        {
            "REMORA_MCP_PROFILE": "enterprise",
            "REMORA_WORKER_URL": "https://remora.corp.example",
            "RAG_WORKER_URL": "https://rag.corp.example",
            "LAW_SEARCH_WORKER_URL": "https://law.corp.example",
            "AGENT_CONTROL_URL": "https://control.corp.example",
        }
    )
    assert profile == "enterprise"
    assert urls["remora"] == "https://remora.corp.example"
    assert urls["law"] == "https://law.corp.example"
    # Never the demo endpoints:
    assert "razorsharp" not in "".join(urls.values())


def test_enterprise_missing_endpoint_refuses_startup(mcp) -> None:
    with pytest.raises(SystemExit) as exc:
        mcp.resolve_profile(
            {
                "REMORA_MCP_PROFILE": "enterprise",
                "REMORA_WORKER_URL": "https://remora.corp.example",
                # RAG_WORKER_URL and LAW_SEARCH_WORKER_URL missing
            }
        )
    assert "no" in str(exc.value).lower() and "fallback" in str(exc.value).lower()


def test_unknown_profile_refuses_startup(mcp) -> None:
    with pytest.raises(SystemExit):
        mcp.resolve_profile({"REMORA_MCP_PROFILE": "production"})


def test_no_silent_fallback_between_profiles(mcp) -> None:
    # local never yields demo endpoints; enterprise failure exits instead of
    # degrading. The demo endpoints appear ONLY under an explicit 'demo'.
    _, local_urls = mcp.resolve_profile({})
    assert "razorsharp" not in "".join(local_urls.values())
