# SPDX-License-Identifier: BUSL-1.1
"""SAP v7 addenda Q6/Q7: run gate, budget guard and registry labellers (§12.2, §15).

Every model client is a fake and sockets are blocked: these tests spend
nothing and reach no network.
"""
from __future__ import annotations

import importlib.util
import json
import socket
from types import SimpleNamespace

import pytest

from experiments.sap_v7_addenda import budget as b
from experiments.sap_v7_addenda import registry as reg
from experiments.sap_v7_addenda import seal


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access in an offline test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ── run gate (§15.1) ─────────────────────────────────────────────────────


def _manifest(tmp_path, files, status=seal.STATUS_LOCKED, seed=seal.SEED, **extra):
    body = {"status": status, "seed": seed, "files": files, **extra}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _tree(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one\r\ntwo\n")
    return {"a.txt": seal.lf_sha256(tmp_path / "a.txt")}


def test_lf_sha256_matches_ots_seal(repo_root, tmp_path):
    spec = importlib.util.spec_from_file_location("ots_seal_for_test",
                                                  repo_root / "scripts" / "ots_seal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _tree(tmp_path)
    assert seal.lf_sha256(tmp_path / "a.txt") == mod.lf_sha256(tmp_path / "a.txt")


def test_gate_refuses_without_manifest(tmp_path):
    with pytest.raises(seal.RunRefused, match="no manifest"):
        seal.open_locked_manifest(tmp_path / "missing.json", tmp_path, [])


@pytest.mark.parametrize("status", ["sealed_never_run", "draft", None])
def test_gate_refuses_unlocked_status(tmp_path, status):
    path = _manifest(tmp_path, _tree(tmp_path), status=status)
    with pytest.raises(seal.RunRefused, match="only 'locked_never_run'"):
        seal.open_locked_manifest(path, tmp_path, ["a.txt"])


def test_gate_refuses_evaluated(tmp_path):
    path = _manifest(tmp_path, _tree(tmp_path), status=seal.STATUS_EVALUATED)
    with pytest.raises(seal.RunRefused, match="second run is not blind"):
        seal.open_locked_manifest(path, tmp_path, ["a.txt"])


def test_gate_refuses_wrong_seed(tmp_path):
    path = _manifest(tmp_path, _tree(tmp_path), seed=1)
    with pytest.raises(seal.RunRefused, match="seed"):
        seal.open_locked_manifest(path, tmp_path, ["a.txt"])


def test_gate_refuses_unlisted_required_file(tmp_path):
    path = _manifest(tmp_path, _tree(tmp_path))
    with pytest.raises(seal.RunRefused, match="not in the manifest"):
        seal.open_locked_manifest(path, tmp_path, ["a.txt", "harness.py"])


def test_gate_refuses_changed_or_missing_file(tmp_path):
    files = _tree(tmp_path)
    path = _manifest(tmp_path, {**files, "gone.txt": "0" * 64})
    with pytest.raises(seal.RunRefused, match="gone.txt"):
        seal.open_locked_manifest(path, tmp_path, ["a.txt"])
    path = _manifest(tmp_path, files)
    (tmp_path / "a.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(seal.RunRefused, match="changed after sealing"):
        seal.open_locked_manifest(path, tmp_path, ["a.txt"])


def test_gate_passes_then_refuses_a_second_run(tmp_path):
    path = _manifest(tmp_path, _tree(tmp_path))
    lock = seal.open_locked_manifest(path, tmp_path, ["a.txt"])
    assert seal.require_lock(lock, "test") is lock
    seal.mark_evaluated(lock, raw_log="x.json")
    assert json.loads(path.read_text())["status"] == seal.STATUS_EVALUATED
    with pytest.raises(seal.RunRefused, match="second run"):
        seal.open_locked_manifest(path, tmp_path, ["a.txt"])


def test_a_lock_cannot_be_forged(tmp_path):
    with pytest.raises(seal.RunRefused):
        seal.LockedManifest(path=tmp_path, body={"status": seal.STATUS_LOCKED})
    with pytest.raises(seal.RunRefused):
        seal.require_lock(None, "reading the test split")
    with pytest.raises(seal.RunRefused):
        seal.require_lock(SimpleNamespace(path=tmp_path, body={}), "reading the test split")


def test_no_study_manifest_exists_and_both_runners_refuse(repo_root, capsys):
    """§15.5 item 7 is not done: no locked manifest exists, so --run refuses."""
    assert not (repo_root / "data" / "injection_injecagent_v1" / "manifest.json").exists()
    assert not (repo_root / "data" / "routing_bench_bfcl_mt_v1" / "manifest.json").exists()
    for script, extra in (("run_injection_eval.py", ["--injecagent", "/nonexistent"]),
                          ("run_routing_baselines.py", ["--data", "/nonexistent"])):
        spec = importlib.util.spec_from_file_location(script[:-3], repo_root / "scripts" / script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.main(["--run", *extra]) == 2
        assert "REFUSING: no manifest" in capsys.readouterr().err


def test_runner_refuses_a_manifest_whose_hashes_differ(repo_root, tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("rie", repo_root / "scripts" / "run_injection_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    files = {rel: "0" * 64 for rel in mod.REQUIRED_FILES}
    path = _manifest(tmp_path, files)
    assert mod.run(tmp_path, path) == 2
    assert "changed after sealing" in capsys.readouterr().err


# ── budget guard (§15.2) ────────────────────────────────────────────────


class _FakeSDK:
    def __init__(self, response):
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._response = response

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _anthropic_response(text="ok", usage=None, stop="end_turn", blocks=None):
    usage = usage if usage is not None else {"input_tokens": 100, "output_tokens": 20,
                                             "cache_creation_input_tokens": 5,
                                             "cache_read_input_tokens": 7}
    return SimpleNamespace(content=blocks or [{"type": "text", "text": text}],
                           stop_reason=stop, usage=usage)


def test_anthropic_usage_counts_cache_tokens_as_input():
    assert b.anthropic_usage(_anthropic_response()) == b.Usage(112, 20)


@pytest.mark.parametrize("usage", [None, {"output_tokens": 3}, {"input_tokens": -1, "output_tokens": 1},
                                   {"input_tokens": 1, "output_tokens": True}])
def test_missing_or_bad_usage_stops_the_run(usage):
    response = SimpleNamespace(usage=usage)
    with pytest.raises(b.UsageMissing):
        b.anthropic_usage(response)
    assert issubclass(b.UsageMissing, b.BudgetExceeded)


def test_openai_usage_fields():
    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4))
    assert b.openai_usage(response) == b.Usage(9, 4)
    with pytest.raises(b.UsageMissing):
        b.openai_usage(SimpleNamespace(usage=SimpleNamespace(prompt_tokens=9)))


def _request(**kw):
    base = dict(model="claude-sonnet-5-5", messages=[{"role": "user", "content": "hi"}],
                max_tokens=2048)
    base.update(kw)
    return b.ModelRequest(**base)


def test_budgeted_client_stops_before_the_cap_without_calling():
    sdk = _FakeSDK(_anthropic_response())
    guard = b.BudgetGuard(cap_usd=0.001, prices={"claude-sonnet-5-5": (2.0, 10.0)})
    client = b.BudgetedClient(b.AnthropicClient(sdk), guard)
    with pytest.raises(b.BudgetExceeded, match="could exceed"):
        client.send(_request())
    assert sdk.calls == [] and guard.spent_usd == 0.0


def test_budgeted_client_records_usage_from_the_response():
    sdk = _FakeSDK(_anthropic_response())
    guard = b.BudgetGuard(cap_usd=10.0, prices={"claude-sonnet-5-5": (2.0, 10.0)})
    reply = b.BudgetedClient(b.AnthropicClient(sdk), guard).send(_request())
    assert reply.text == "ok" and guard.calls == 1
    assert guard.spent_usd == pytest.approx((112 * 2.0 + 20 * 10.0) / 1e6)


def test_unpriced_model_is_refused():
    guard = b.BudgetGuard(cap_usd=10.0, prices={})
    with pytest.raises(b.BudgetExceeded, match="no price"):
        b.BudgetedClient(b.AnthropicClient(_FakeSDK(_anthropic_response())), guard).send(_request())


def test_worst_case_bounds_the_request_bytes():
    req = _request(messages=[{"role": "user", "content": "é" * 1000}])
    assert b.worst_case_input_tokens(req) >= 2000


def test_anthropic_request_shape_follows_the_plan():
    kw = b.AnthropicClient(_FakeSDK(None)).kwargs(_request(
        effort="low", json_schema={"type": "object"}, system="s",
        tools=[{"name": "f", "description": "d", "parameters": {
            "type": "dict", "properties": {"x": {"type": "float"}, "y": {"type": "any"}}}}]))
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "low",
                                   "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert "temperature" not in kw and "top_p" not in kw
    assert kw["tools"][0]["input_schema"] == {"type": "object",
                                              "properties": {"x": {"type": "number"}, "y": {}}}
    with pytest.raises(ValueError):
        b.AnthropicClient(_FakeSDK(None)).kwargs(_request(sampling={"temperature": 0.0}))


def test_anthropic_reply_keeps_tool_calls_and_raw_blocks():
    blocks = [{"type": "thinking", "thinking": "", "signature": "s"},
              {"type": "tool_use", "id": "t1", "name": "cd", "input": {"folder": "a"}}]
    reply = b.AnthropicClient(_FakeSDK(_anthropic_response(blocks=blocks, stop="tool_use"))).send(
        _request())
    assert reply.tool_calls == ({"id": "t1", "name": "cd", "arguments": {"folder": "a"}},)
    assert reply.raw_content == tuple(blocks)


def test_openai_compatible_request_and_reply():
    message = SimpleNamespace(content="", tool_calls=[SimpleNamespace(
        id="c1", function=SimpleNamespace(name="cd", arguments='{"folder": "a"}'))])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
                               usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2))
    sdk = _FakeSDK(response)
    client = b.OpenAICompatibleClient(sdk)
    reply = client.send(_request(model="llama-3.3-70b-versatile", system="s",
                                 sampling={"temperature": 0.0, "top_p": 1.0},
                                 json_schema={"type": "object"}))
    sent = sdk.calls[0]
    assert sent["temperature"] == 0.0 and sent["top_p"] == 1.0
    assert sent["messages"][0] == {"role": "system", "content": "s"}
    assert sent["response_format"]["type"] == "json_schema"
    assert reply.tool_calls[0]["arguments"] == {"folder": "a"} and reply.usage == b.Usage(3, 2)


# ── registry labellers (§12.2) ──────────────────────────────────────────


def test_l1_uses_the_mutating_tokens_by_substring():
    assert reg.l1_label("GmailSendEmail") == reg.Label("write", "high")
    assert reg.l1_label("BankManagerGetAccount") == reg.Label("read", "low")
    # The known gap §12.2 names: "grant" has no _MUTATING token.
    assert reg.l1_label("AugustSmartLockGrantGuestAccess").action_type == "read"
    from remora.toolcall.routing.evaluate import _MUTATING
    assert reg.mutating_tokens() == tuple(_MUTATING)


def test_combination_keeps_the_more_restrictive_label():
    assert reg.combine(reg.Label("read", "low"), reg.Label("write", "medium")) == reg.Label("write", "medium")
    assert reg.combine(reg.Label("write", "high"), reg.Label("read", "critical")) == reg.Label("write", "critical")
    assert reg.combine(reg.Label("read", "low"), reg.Label("read", "low")) == reg.Label("read", "low")


def _docs():
    return [reg.ToolDoc("KitSend", "Send a thing.", {"parameters": []}, "Kit", "Comms"),
            reg.ToolDoc("KitList", "List things.", {"parameters": []}, "Kit", "Comms")]


def test_l2_prompt_holds_only_tool_documents():
    template = reg.LABELLER_PROMPT.read_text(encoding="utf-8")
    text = reg.render_l2_prompt(template, "Kit", _docs())
    assert "KitSend" in text and "Send a thing." in text and "{tool_documents}" not in text
    assert "{toolkit}" not in text


@pytest.mark.parametrize("reply", [
    "not json", '{"tools": "x"}', '{"tools": [{"name": "Other", "action_type": "read", "risk_tier": "low"}]}',
    '{"tools": [{"name": "KitSend", "action_type": "send", "risk_tier": "low"}]}',
    '{"tools": [{"name": "KitSend", "action_type": "write", "risk_tier": "high"}]}',
])
def test_parse_l2_rejects_incomplete_or_invalid_replies(reply):
    with pytest.raises(reg.L2Invalid):
        reg.parse_l2(reply, ["KitSend", "KitList"])


class _ScriptedClient:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def send(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


def _reply(text, stop="end_turn"):
    return b.ModelReply(text, stop, b.Usage(1, 1))


def test_l2_retries_once_then_raises():
    good = json.dumps({"tools": [{"name": "KitSend", "action_type": "write", "risk_tier": "high"},
                                 {"name": "KitList", "action_type": "read", "risk_tier": "low"}]})
    client = _ScriptedClient([_reply("", "refusal"), _reply(good)])
    labels = reg.l2_label_toolkit(client, "{toolkit} {tool_documents}", "Kit", _docs())
    assert labels["KitSend"] == reg.Label("write", "high")
    req = client.requests[0]
    assert req.model == "claude-sonnet-5-5" and req.effort == "low" and req.json_schema
    with pytest.raises(reg.L2Invalid, match="after one retry"):
        reg.l2_label_toolkit(_ScriptedClient([_reply("x"), _reply("y")]), "{toolkit}", "Kit", _docs())


def test_registry_document_loads_as_deployment_metadata(tmp_path):
    from remora.toolcall.deployment_registry import load_deployment_tool_metadata

    registry = reg.build_registry(_docs(), {"KitSend": reg.Label("write", "medium"),
                                            "KitList": reg.Label("read", "medium")})
    assert registry["KitSend"]["risk_tier"] == "high"  # L1 high beats L2 medium
    for which in ("combined", "l1", "l2"):
        path = tmp_path / f"{which}.json"
        path.write_text(json.dumps(reg.metadata_document(registry, which)), encoding="utf-8")
        loaded = load_deployment_tool_metadata(path)
        assert set(loaded) == {"KitSend", "KitList"}
    assert reg.variant(registry, "l2")["KitList"] == reg.Label("read", "medium")
    with pytest.raises(ValueError):
        reg.build_registry(_docs(), {"KitSend": reg.Label("write", "high")})


def test_cohen_kappa():
    assert reg.cohen_kappa(["read", "write"], ["read", "write"]) == 1.0
    assert reg.cohen_kappa(["read", "read", "write", "write"],
                           ["read", "write", "read", "write"]) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        reg.cohen_kappa([], [])
