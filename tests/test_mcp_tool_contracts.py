# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every MCP tool parameter does what its description says (quality program Q6.1, Q6.2).

A parameter either changes the request the handler sends, or its description
says it is not sent (echoed, reported back, ignored). Two descriptions claimed
a domain that was never sent until 2026-09-28; this test reads every tool so
the next one fails here instead of in a user's analysis.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))
import mcp_remora as m  # noqa: E402

#: Handlers that compute locally and send nothing; their parameters are
#: checked against the handler's output instead of an outgoing request.
LOCAL = {"remora_session_status", "remora_status"}
#: Samples that make a parameter reachable (the citation tool only calls out
#: when the text contains a citation it recognises).
SAMPLES = {
    ("remora_verify_legal_citations", "document_text"): ("Se Rt. 2005 s. 1234.", "Se Rt. 2010 s. 555."),
    ("remora_verify_legal_citations", "claimed_principles"): ("prinsipp A", "prinsipp B"),
}
_DECLARED_NOT_SENT = re.compile(r"not sent|reported back|echoed|ignor", re.IGNORECASE)
_FAKE = {"verdict": True, "confidence": 0.8, "claim": "c", "summary": "s", "oracle_calls": 3,
         "answer": True, "sources": [], "results": [], "session_id": "s1", "status": "ok"}


@pytest.fixture(autouse=True)
def _all_endpoints(monkeypatch):
    for attr, value in (("REMORA_WORKER", m._DEMO_REMORA), ("RAG_WORKER", m._DEMO_RAG),
                        ("LAW_SEARCH_WORKER", m._DEMO_LAW), ("CODEGRAPH_URL", "https://codegraph.example"),
                        ("REPO_SEARCH_URL", "https://search.example"), ("AGENT_CONTROL", "https://control.example"),
                        ("AGENT_SECRET", "test-secret")):
        monkeypatch.setattr(m, attr, value)


def _sample(tool: str, name: str, prop: dict, which: int):
    if (tool, name) in SAMPLES:
        return SAMPLES[(tool, name)][which]
    if len(prop.get("enum", [])) > 1:
        return prop["enum"][which]
    return {"string": ("alpha text", "beta text"), "integer": (3, 7), "boolean": (False, True),
            "object": ({"a": 1}, {"a": 2})}.get(prop.get("type", "string"), ("x", "y"))[which]


def _run(tool: str, args: dict) -> tuple[list, str]:
    sent: list = []

    def record(kind):
        def fn(target, payload=None, **_):
            sent.append((kind, target, json.dumps(payload, sort_keys=True, default=str)))
            return _FAKE
        return fn

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(_FAKE).encode()

    def urlopen(req, **_):
        # Handlers that call urllib directly (the audit log) are recorded too.
        sent.append(("URLOPEN", req.full_url, (req.data or b"").decode()))
        return _Resp()

    with mock.patch.object(m, "_post", record("POST")), mock.patch.object(m, "_get", record("GET")), \
         mock.patch.object(m, "_agent_post", record("AGENT")), \
         mock.patch.object(m.urllib.request, "urlopen", urlopen):
        return sent, str(m.HANDLERS[tool](copy.deepcopy(args)))


CASES = [(t["name"], p) for t in m.TOOLS for p in t["inputSchema"]["properties"]]


@pytest.mark.parametrize("tool,param", CASES, ids=[f"{t}.{p}" for t, p in CASES])
def test_parameter_reaches_the_request_or_says_it_does_not(tool: str, param: str) -> None:
    spec = next(t for t in m.TOOLS if t["name"] == tool)
    props = spec["inputSchema"]["properties"]
    if len(props[param].get("enum", [])) == 1:
        pytest.skip("single-valued enum")
    base = {p: _sample(tool, p, pr, 0) for p, pr in props.items()}
    changed = {**base, param: _sample(tool, param, props[param], 1)}
    sent0, out0 = _run(tool, base)
    sent1, out1 = _run(tool, changed)
    if tool == "remora_session_status":
        pytest.skip("checked by test_session_dir_selects_the_session_state")
    if tool in LOCAL:
        assert out0 != out1, f"{tool}.{param} changes nothing the local handler returns"
        return
    if sent0 != sent1:
        return
    text = props[param].get("description", "") + " " + spec["description"]
    assert _DECLARED_NOT_SENT.search(text), (
        f"{tool}.{param} does not change the request, and neither description says it is not sent")


def _worker_sizes() -> set[str]:
    toml = (ROOT / "workers/rag-oracle/wrangler.toml").read_text(encoding="utf-8")
    return {s.upper() for s in re.findall(r"llama-[\d.]+-(\d+b)", toml, re.IGNORECASE)}


def test_model_sizes_in_descriptions_match_the_worker_config() -> None:
    sizes = _worker_sizes()
    assert sizes, "could not read the RAG worker's models"
    for tool in m.TOOLS:
        texts = [tool["description"]] + [p.get("description", "") for p in tool["inputSchema"]["properties"].values()]
        for size in re.findall(r"\b(\d+B)\b", " ".join(texts)):
            assert size in sizes, f"{tool['name']} names a {size} model the RAG worker does not configure"


def test_descriptions_name_no_model_family_or_count() -> None:
    banned = re.compile(r"\b(LLaMA|Mistral|GPT-?\d|Gemini|Groq|OpenRouter)\b|\b\d+ (independent )?(AI )?(models|oracles)\b",
                        re.IGNORECASE)
    for tool in m.TOOLS:
        assert not banned.search(tool["description"]), f"{tool['name']}: {banned.search(tool['description']).group(0)}"


def test_session_dir_selects_the_session_state(monkeypatch, tmp_path) -> None:
    """The local session tool reads the directory it is given, not a default."""
    import remora.agent_hook.intent_anchor as ia
    import remora.agent_hook.lyapunov_tracker as lt

    seen = []
    real_tracker, real_anchor = lt.LyapunovTracker, ia.IntentAnchor
    monkeypatch.setattr(lt, "LyapunovTracker", lambda session_dir=None: (seen.append(session_dir), real_tracker(session_dir=session_dir))[1])
    monkeypatch.setattr(ia, "IntentAnchor", lambda session_dir=None: (seen.append(session_dir), real_anchor(session_dir=session_dir))[1])
    m.handle_remora_session_status({"session_dir": str(tmp_path)})
    assert seen == [tmp_path, tmp_path]
