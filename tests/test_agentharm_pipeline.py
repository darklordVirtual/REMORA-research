"""Bug-class regression tests for the AgentHarm validation pipeline.

Covers: base-URL validation, Inspect/Cloudflare model mapping, Wilson CI,
confusion matrix, missing-baseline non-zero exit, status:invalid summary,
and tool_risk_map loading. These run without inspect-ai / openai installed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.agentharm import cf_compat
from experiments.agentharm import score_guardrail as sg

REPO = Path(__file__).resolve().parent.parent
RISK_MAP = REPO / "experiments" / "agentharm" / "tool_risk_map.yaml"


# ── base URL validation ──────────────────────────────────────────────
def test_validate_base_url_rejects_chat_completions():
    with pytest.raises(ValueError):
        cf_compat.validate_base_url(
            "https://gateway.ai.cloudflare.com/v1/acct/gw/compat/chat/completions"
        )


def test_validate_base_url_rejects_trailing_slash_chat_completions():
    with pytest.raises(ValueError):
        cf_compat.validate_base_url("https://x/compat/chat/completions/")


def test_validate_base_url_accepts_compat():
    url = "https://gateway.ai.cloudflare.com/v1/acct/gw/compat/"
    assert cf_compat.validate_base_url(url).endswith("/compat")


def test_validate_base_url_accepts_unified_billing_rest_base():
    url = "https://api.cloudflare.com/client/v4/accounts/acct/ai/v1/"
    assert cf_compat.validate_base_url(url).endswith("/ai/v1")


def test_resolve_base_url_builds_unified_billing_rest_endpoint():
    env = {"CLOUDFLARE_ACCOUNT_ID": "acct-123"}
    assert cf_compat.resolve_base_url(env) == (
        "https://api.cloudflare.com/client/v4/accounts/acct-123/ai/v1"
    )


def test_resolve_api_key_prefers_cloudflare_token_names():
    env = {
        "CLOUDFLARE_API_TOKEN": "cf-token",
        "OPENAI_API_KEY": "openai-token",
    }
    assert cf_compat.resolve_api_key(env) == "cf-token"


def test_validate_base_url_empty_raises():
    with pytest.raises(ValueError):
        cf_compat.validate_base_url("")


# ── model name mapping ───────────────────────────────────────────────
@pytest.mark.parametrize("cf,expected", [
    ("openai/gpt-5", "openai/openai/gpt-5"),
    ("openai/openai/gpt-5", "openai/openai/gpt-5"),
    ("gpt-4o-mini", "openai/gpt-4o-mini"),
])
def test_to_inspect_model(cf, expected):
    assert cf_compat.to_inspect_model(cf) == expected


# ── secret masking ───────────────────────────────────────────────────
def test_mask_secret_never_reveals():
    secret = "sk-supersecretvalue1234"
    masked = cf_compat.mask_secret(secret)
    assert secret not in masked
    assert cf_compat.mask_secret(None) == "<unset>"
    assert cf_compat.mask_secret("") == "<unset>"


# ── Wilson CI ────────────────────────────────────────────────────────
def test_wilson_ci_zero_n():
    assert sg.wilson_ci(0, 0) == (0.0, 1.0)


def test_wilson_ci_bounds_and_known_value():
    lo, hi = sg.wilson_ci(8, 10)
    assert 0.0 <= lo < 0.8 < hi <= 1.0
    # half-and-half stays centered near 0.5
    lo2, hi2 = sg.wilson_ci(50, 100)
    assert lo2 < 0.5 < hi2


# ── confusion matrix ─────────────────────────────────────────────────
def test_compute_metrics_perfect_blocker():
    baseline_harmful = [{"task_id": "h1", "harm_score": 1.0, "completed": True},
                        {"task_id": "h2", "harm_score": 1.0, "completed": True}]
    arm_harmful = [{"task_id": "h1", "harm_score": 0.0, "completed": True},
                   {"task_id": "h2", "harm_score": 0.0, "completed": True}]
    baseline_benign = [{"task_id": "b1", "completed": True}]
    arm_benign = [{"task_id": "b1", "completed": True}]
    m = sg.compute_metrics(baseline_harmful, arm_harmful,
                           baseline_benign, arm_benign, [], "remora_full")
    assert m["TP"] == 2 and m["FN"] == 0
    assert m["recall"] == 1.0
    assert m["FP"] == 0 and m["TN"] == 1
    assert m["FPR"] == 0.0


def test_compute_metrics_false_positive():
    baseline_harmful = [{"task_id": "h1", "harm_score": 1.0}]
    arm_harmful = [{"task_id": "h1", "harm_score": 1.0}]  # not blocked -> FN
    baseline_benign = [{"task_id": "b1", "completed": True}]
    arm_benign = [{"task_id": "b1", "completed": False}]  # blocked benign -> FP
    m = sg.compute_metrics(baseline_harmful, arm_harmful,
                           baseline_benign, arm_benign, [], "remora_full")
    assert m["FN"] == 1 and m["recall"] == 0.0
    assert m["FP"] == 1 and m["FPR"] == 1.0


# ── missing baseline → non-zero exit + status:invalid ────────────────
def test_main_missing_baseline_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sg, "ENVELOPE_LOG", tmp_path / "envelopes.jsonl")
    rc = sg.main([])
    assert rc == 2
    summary = json.loads((tmp_path / "guardrail_scores.json").read_text())
    assert summary["status"] == "invalid"
    assert summary["headline_claims_allowed"] is False


def test_main_missing_baseline_allow_missing_exits_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sg, "ENVELOPE_LOG", tmp_path / "envelopes.jsonl")
    rc = sg.main(["--allow-missing"])
    assert rc == 0
    summary = json.loads((tmp_path / "guardrail_scores.json").read_text())
    assert summary["status"] == "invalid"


def test_write_invalid_summary_blocks_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "RESULTS_DIR", tmp_path)
    out = sg.write_invalid_summary("no baseline")
    data = json.loads(out.read_text())
    assert data["headline_claims_allowed"] is False
    assert data["results"] == []


# ── tool_risk_map loads and has default ──────────────────────────────
def test_tool_risk_map_loads_with_default():
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(RISK_MAP.read_text())
    tools = data["tools"]
    assert "_default_unknown" in tools
    assert tools["_default_unknown"]["risk_tier"] == "high"
