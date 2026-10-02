# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Per-vertical shadow profiles: one deployment, several languages and domains.

A Norwegian ISP and an English bank need different question sets,
thresholds and language caveats. These tests pin the profile file contract,
that each tenant is evaluated under its own profile, and that the reviewer
caveats follow the profile.

Scope (declared, not exhaustive): configuration and routing with
deterministic providers. Nothing here is evidence about a live model or
about any vertical's calibration.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from remora.decision_providers import DeterministicDecisionProvider
from remora.decision_providers.questions import REMORA_QUESTIONS_V1, REMORA_QUESTIONS_V2_1
from remora.decision_providers.review import NON_ENGLISH, UNCALIBRATED, caveats_for, reviewer_view
from remora.decision_providers.shadow import JsonlShadowSink
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from servers import semantic_shadow as ss

PROFILES = """
profiles:
  isp-no:
    questions: v2.1
    thresholds: {intent: 0.85, target: 0.85, injection: 0.9, drift: 0.5}
    language: no
  bank-en:
    questions: v1
    thresholds: {intent: 0.9, target: 0.9, injection: 0.5, drift: 0.4}
    language: en
    calibration: {status: calibrated, study: artifacts/bank-calibration, corpus_sha256: abcdef0123456789}
tenants:
  luftfiber: isp-no
  nordbank: bank-en
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "profiles.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_profile_file_loads_every_vertical(tmp_path) -> None:
    profiles, tenants = ss.load_profiles(_write(tmp_path, PROFILES))
    assert tenants == {"luftfiber": "isp-no", "nordbank": "bank-en"}
    isp = profiles["isp-no"]
    assert isp.language == "no", "YAML reads a bare no as False; the loader must keep the code"
    assert isp.questions is REMORA_QUESTIONS_V2_1
    assert isp.thresholds.possible_injection == 0.9
    assert isp.calibration == {"status": "uncalibrated"}
    assert profiles["bank-en"].calibration["status"] == "calibrated"


def test_json_is_accepted_too(tmp_path) -> None:
    import yaml

    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(yaml.safe_load(PROFILES)), encoding="utf-8")
    profiles, _ = ss.load_profiles(path)
    assert set(profiles) == {"isp-no", "bank-en"}


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda t: t.replace("language: en", "langauge: en"), "unknown keys"),
        (lambda t: t.replace(", drift: 0.5}", "}"), "no threshold has a default"),
        (lambda t: t.replace("nordbank: bank-en", "nordbank: bank-se"), "undefined profiles"),
        (lambda t: t.replace(", corpus_sha256: abcdef0123456789", ""), "must name its study"),
        (lambda t: t.replace("questions: v2.1", "questions: v9"), "unknown question set"),
        (lambda t: t.replace("injection: 0.9", "injection: 0.9, accept: 0.1"), "unknown threshold"),
        (lambda t: t + "extra: 1\n", "exactly the keys"),
    ],
)
def test_a_wrong_profile_file_is_refused_whole(tmp_path, edit, message) -> None:
    with pytest.raises(ValueError, match=message):
        ss.load_profiles(_write(tmp_path, edit(PROFILES)))


def test_profiles_and_the_single_profile_variables_together_are_refused(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("REMORA_SEMANTIC_SHADOW", "1")
    monkeypatch.setenv("REMORA_SEMANTIC_SHADOW_LOG", str(tmp_path / "s.jsonl"))
    monkeypatch.setenv("REMORA_SEMANTIC_SHADOW_PROFILES", str(_write(tmp_path, PROFILES)))
    monkeypatch.setenv("REMORA_SEMANTIC_SHADOW_TENANTS", "acme")
    with pytest.raises(ValueError, match="use one or the other"):
        ss.build_semantic_shadow_from_env(engine=object(), provider_factory=lambda v, m: object())


class _Inline:
    def submit(self, fn, *args):
        fn(*args)


def _answers(questions, **overrides):
    base = {q.id: 0.03 for q in questions} | {
        "intent_match": 0.95, "target_matches_request": 0.95, "scope_drift": 0.05,
        "action_reversibility": 0.2, "semantic_risk": 1.0,
    }
    return base | overrides


def _shadow_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_SEMANTIC_SHADOW", "1")
    monkeypatch.setenv("REMORA_SEMANTIC_SHADOW_LOG", str(tmp_path / "s.jsonl"))
    monkeypatch.setenv("REMORA_SEMANTIC_SHADOW_PROFILES", str(_write(tmp_path, PROFILES)))
    for var in ("REMORA_SEMANTIC_SHADOW_TENANTS", "REMORA_SEMANTIC_SHADOW_QUESTIONS",
                "REMORA_SEMANTIC_SHADOW_THRESHOLDS", "REMORA_SEMANTIC_SHADOW_MODEL"):
        monkeypatch.delenv(var, raising=False)
    built = []

    def factory(version, model):
        questions = REMORA_QUESTIONS_V1 if version.endswith("v1") else REMORA_QUESTIONS_V2_1
        # injection 0.7: past the bank's 0.5 cut, short of the ISP's 0.9 cut
        injection = {"possible_injection": 0.7} if questions is REMORA_QUESTIONS_V1 else {"injection_override": 0.7}
        built.append((version, model))
        return DeterministicDecisionProvider(_answers(questions, **injection), question_set_version=version)

    engine = RemoraDecisionEngine(execution_profile=True)
    shadow = ss.build_semantic_shadow_from_env(engine=engine, provider_factory=factory)
    shadow._executor = _Inline()
    return shadow, engine, built


def _call(shadow, engine, tenant):
    obs = PolicyObservation(question="Change VLAN for C123 to 420", risk_tier="high",
                            action_type="configuration_change", target_environment="prod",
                            intent_authority_present=True)
    action = engine.decide(obs).action
    shadow({"tenant": tenant, "proposal_id": f"p-{tenant}", "observation": obs,
            "proposal": SimpleNamespace(tool_name="t", arguments={"customer_id": "C123"},
                                        untrusted_context="Kunden vil ha VLAN 420."),
            "engine_action": action, "final_action": action})


def test_each_tenant_is_evaluated_under_its_own_profile(monkeypatch, tmp_path) -> None:
    shadow, engine, built = _shadow_from_env(monkeypatch, tmp_path)
    _call(shadow, engine, "luftfiber")
    _call(shadow, engine, "nordbank")
    sink = JsonlShadowSink(tmp_path / "s.jsonl")
    isp, bank = sink.find("p-luftfiber", "luftfiber"), sink.find("p-nordbank", "nordbank")
    assert isp["profile"] == "isp-no" and isp["language"] == "no"
    assert isp["question_set_version"] == "remora-semantic-v2.1"
    assert isp["thresholds"]["possible_injection"] == 0.9
    assert isp["shadow_action"] == "VERIFY", "0.7 is short of the ISP profile's 0.9 cut"
    assert bank["profile"] == "bank-en" and bank["question_set_version"] == "remora-semantic-v1"
    assert bank["shadow_action"] == "ESCALATE", "0.7 is past the bank profile's 0.5 cut"
    assert sorted(v for v, _m in built) == ["remora-semantic-v1", "remora-semantic-v2.1"]
    assert {m for _v, m in built} == {"jev-1.13.0"}


def test_a_tenant_without_a_profile_is_not_sent(monkeypatch, tmp_path) -> None:
    shadow, engine, _built = _shadow_from_env(monkeypatch, tmp_path)
    _call(shadow, engine, "unlisted")
    assert shadow.skipped_tenant == 1
    assert shadow.lookup("p-unlisted", "unlisted") == ("tenant_not_opted_in", None)


def test_caveats_follow_the_profile(monkeypatch, tmp_path) -> None:
    shadow, engine, _built = _shadow_from_env(monkeypatch, tmp_path)
    _call(shadow, engine, "luftfiber")
    _call(shadow, engine, "nordbank")
    sink = JsonlShadowSink(tmp_path / "s.jsonl")
    isp = reviewer_view(sink.find("p-luftfiber", "luftfiber"))["caveats"]
    bank = reviewer_view(sink.find("p-nordbank", "nordbank"))["caveats"]
    assert UNCALIBRATED in isp and NON_ENGLISH in isp
    assert UNCALIBRATED not in bank and NON_ENGLISH not in bank
    assert bank[0].startswith("Thresholds from calibration study artifacts/bank-calibration")


def test_an_undeclared_language_keeps_the_language_caveat() -> None:
    assert NON_ENGLISH in caveats_for({"language": None})
    assert NON_ENGLISH not in caveats_for({"language": "en"})
