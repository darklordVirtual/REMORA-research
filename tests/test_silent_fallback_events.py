# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""No degradation in the safety path is silent (issue #45, gaps 3 and 5).

Each fallback keeps its semantics -- a layered guard defers to the next
layer, a scaler failure reverts to the raw value, an unverifiable token is
unauthenticated -- but every branch now emits one structured governance
event. These tests pin both halves at every site: the behaviour is unchanged
AND the event fires, because a fix that changed either half alone would be a
regression (of safety, or of the visibility this issue exists for).
"""
from __future__ import annotations

import logging
import urllib.request

import pytest

LOGGER = "remora.governance"


def _events(caplog) -> list[str]:
    return [r.msg % r.args if r.args else str(r.msg) for r in caplog.records
            if r.name == LOGGER]


def _event_names(caplog) -> set[str]:
    out = set()
    for r in caplog.records:
        if r.name == LOGGER and r.args:
            out.add(str(r.args[0]) if isinstance(r.args, tuple) else "")
    # governance_event logs as "%s %s" % (event, rendered)
    return {n for n in out if n}


class _RaisingParser:
    @staticmethod
    def parse(_command):
        raise ValueError("simulated parser crash")


def test_a_bashlex_crash_defers_and_says_so(monkeypatch, caplog) -> None:
    from remora.safety import ast_guard
    monkeypatch.setattr(ast_guard, "_bashlex", _RaisingParser)
    monkeypatch.setattr(ast_guard, "_BASHLEX_AVAILABLE", True)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert ast_guard.parse_and_validate("echo hello") is True
    assert "safety.ast_layer_degraded" in _event_names(caplog)
    assert any("bashlex" in e for e in _events(caplog))


def test_a_sqlglot_crash_defers_and_says_so(monkeypatch, caplog) -> None:
    from remora.safety import ast_guard
    monkeypatch.setattr(ast_guard, "_sqlglot", _RaisingParser)
    monkeypatch.setattr(ast_guard, "_SQLGLOT_AVAILABLE", True)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert ast_guard.parse_and_validate("echo hello") is True
    assert "safety.ast_layer_degraded" in _event_names(caplog)
    assert any("sqlglot" in e for e in _events(caplog))


def test_the_heuristic_layer_still_blocks_when_a_parser_is_down(
    monkeypatch, caplog
) -> None:
    """The reason deferral is acceptable at all: the guard is layered, and a
    destructive command is still caught below the crashed layer."""
    from remora.safety import ast_guard
    monkeypatch.setattr(ast_guard, "_bashlex", _RaisingParser)
    monkeypatch.setattr(ast_guard, "_BASHLEX_AVAILABLE", True)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert ast_guard.parse_and_validate("rm -rf /") is False


def test_a_dead_injection_oracle_is_distinguishable_from_a_disabled_one(
    monkeypatch, caplog
) -> None:
    from remora.agent_hook.result_scanner import ToolResultScanner

    def boom(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    scanner = ToolResultScanner(oracle_enabled=True)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        used, confidence = scanner._oracle_scan("read_file", "excerpt", [])
    # The fallback contract is unchanged: heuristics decide.
    assert (used, confidence) == (False, None)
    # But a DEAD oracle now says so, which a disabled one never does.
    assert "agent_hook.injection_oracle_failed" in _event_names(caplog)


@pytest.mark.parametrize("adapter_module, adapter_cls, adapter_kwargs, idp", [
    ("remora.adapters.identity.entra", "EntraIDAdapter",
     {"tenant_id": "t", "client_id": "c"}, "entra"),
    ("remora.adapters.identity.keycloak", "KeycloakAdapter",
     {"server_url": "https://kc.invalid", "realm": "r", "client_id": "c"},
     "keycloak"),
])
def test_a_rejected_token_is_logged_as_rejection_not_outage(
    adapter_module, adapter_cls, adapter_kwargs, idp, caplog
) -> None:
    """'not-a-jwt' fails locally in header parsing -- no network involved --
    and must surface as identity.token_rejected at INFO, not as an outage."""
    import importlib
    provider = getattr(importlib.import_module(adapter_module), adapter_cls)(
        **adapter_kwargs)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert provider.validate("not-a-jwt") is None
    names = _event_names(caplog)
    assert "identity.token_rejected" in names, names
    assert "identity.verification_unavailable" not in names
    assert any(idp in e for e in _events(caplog))


def test_a_crashed_correlation_model_is_marked_and_logged(caplog) -> None:
    from remora.evidence.provider import OracleProxyEvidenceProvider

    def broken(_providers):
        raise RuntimeError("model exploded")

    provider = OracleProxyEvidenceProvider(mean_rho_fn=broken)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        rho, from_model = provider._mean_rho(["a", "b"])
    assert (rho, from_model) == (0.5, False)
    assert "evidence.correlation_model_failed" in _event_names(caplog)


def test_an_absent_correlation_model_stays_quiet(caplog) -> None:
    """Deliberate absence is a configuration, not a degradation: only the
    crashed-model branch may emit."""
    from remora.evidence.provider import OracleProxyEvidenceProvider
    provider = OracleProxyEvidenceProvider(mean_rho_fn=None)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        rho, from_model = provider._mean_rho(["a", "b"])
    assert (rho, from_model) == (0.5, False)
    assert "evidence.correlation_model_failed" not in _event_names(caplog)


def test_events_never_change_behaviour_when_logging_is_broken(
    monkeypatch, caplog
) -> None:
    """Constraint 2 of the events module: an observability defect must not
    become a governance defect. With the emitter itself broken, the guard
    still answers."""
    from remora.safety import ast_guard
    import remora.observability.events as events

    def exploding_event(*_a, **_k):
        raise RuntimeError("logging pipeline down")

    monkeypatch.setattr(events, "governance_event", exploding_event)
    monkeypatch.setattr(ast_guard, "_bashlex", _RaisingParser)
    monkeypatch.setattr(ast_guard, "_BASHLEX_AVAILABLE", True)
    assert ast_guard.parse_and_validate("echo hello") is True
