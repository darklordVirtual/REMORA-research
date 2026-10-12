# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""QV2-06: the LLM-as-proposer arm may fill and veto, never overrule.

The property that matters is monotonicity against the deterministic
extractor: on a task the extractor grounds, the combined intent yields the
deterministic goal-match verdict or UNKNOWN, and the engine never ACCEPTs a
call it would not have ACCEPTed without the proposer.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.toolcall.routing.bfcl_semantic_bundle import author_contract
from remora.toolcall.routing.goal_match import (
    GoalMatch,
    TaskIntent,
    match_tool_to_intent,
)
from remora.toolcall.routing.intent_proposer import (
    INTENT_PROMPT_TEMPLATE,
    PROPOSER_VERSION,
    RecordReplayProvider,
    ReplayMiss,
    combine_intents,
    intents_agree,
    parse_intent_proposal,
    prompt_sha256,
    propose_derivations,
    propose_intent,
)

TASK = "Please find a bus from Oslo to Bergen and book a hotel there."
LEX = {"bus", "hotel", "flight"}


class FakeProvider:
    model_id = "fake-model"

    def __init__(self, response: str | Exception) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _ans(**kw: object) -> str:
    return json.dumps(kw)


# ── parsing: every check goal_match would apply, recorded with a reason ────

def test_valid_proposal_becomes_intent() -> None:
    p = parse_intent_proposal(
        _ans(effect="read", action_span="find a bus", resource="bus",
             resource_span="a bus"), TASK, LEX)
    assert p.reason == "accepted"
    assert p.intent is not None
    assert p.intent.resource_type == "bus"
    assert p.intent.proposed_by == PROPOSER_VERSION


def test_prose_and_fences_around_the_json_are_tolerated() -> None:
    raw = "Sure!\n```json\n" + _ans(
        effect="read", action_span="find a bus", resource="bus",
        resource_span="a bus") + "\n```"
    assert parse_intent_proposal(raw, TASK, LEX).reason == "accepted"


@pytest.mark.parametrize("raw,reason", [
    ("no json here", "not_json"),
    ("[1, 2]", "not_an_object"),
    (_ans(effect=None), "declined"),
    (_ans(effect="read", action_span="find a bus", resource="bus"),
     "missing_field"),
    (_ans(effect="teleport", action_span="find a bus", resource="bus",
          resource_span="a bus"), "unknown_effect"),
    (_ans(effect="read", action_span="find a bus", resource="train",
          resource_span="a bus"), "resource_not_in_lexicon"),
    (_ans(effect="read", action_span="find a bus", resource="hotel",
          resource_span="a bus"), "resource_not_in_its_span"),
    (_ans(effect="read", action_span="find a bus", resource="flight",
          resource_span="a flight"), "resource_span_not_in_task"),
    (_ans(effect="read", action_span="locate a bus", resource="bus",
          resource_span="a bus"), "action_not_grounded"),
    (_ans(effect="cancel", action_span="find a bus", resource="bus",
          resource_span="a bus"), "action_not_grounded"),
])
def test_unusable_proposals_are_dropped_with_a_reason(raw: str,
                                                      reason: str) -> None:
    p = parse_intent_proposal(raw, TASK, LEX)
    assert p.intent is None
    assert p.reason == reason


def test_negated_effect_is_not_grounded() -> None:
    task = "Do not cancel the booking, just show it."
    p = parse_intent_proposal(
        _ans(effect="cancel", action_span="not cancel the booking",
             resource="booking", resource_span="the booking"),
        task, {"booking"})
    assert p.intent is None and p.reason == "action_not_grounded"


# ── isolation: the intent prompt never carries the call under review ───────

def test_intent_prompt_carries_task_and_lexicon_only() -> None:
    fake = FakeProvider(_ans(effect=None))
    propose_intent(TASK, LEX, fake)
    (prompt,) = fake.prompts
    assert TASK in prompt
    for term in LEX:
        assert term in prompt
    # The signature has no slot for a tool or its arguments; this pins that
    # the template has none either.
    assert "{tool" not in INTENT_PROMPT_TEMPLATE
    assert "{argument" not in INTENT_PROMPT_TEMPLATE


def test_provider_failure_is_a_silent_proposer() -> None:
    p = propose_intent(TASK, LEX, FakeProvider(RuntimeError("503")))
    assert p.intent is None and p.reason == "provider_error"


# ── record and replay ──────────────────────────────────────────────────────

def test_record_then_replay_is_byte_identical(tmp_path: Path) -> None:
    cache = tmp_path / "cache.jsonl"
    live = FakeProvider(_ans(effect="read", action_span="find a bus",
                             resource="bus", resource_span="a bus"))
    rec = RecordReplayProvider(cache, model_id="fake-model", mode="record",
                               provider=live)
    first = propose_intent(TASK, LEX, rec)
    rep = RecordReplayProvider(cache, model_id="fake-model", mode="replay")
    second = propose_intent(TASK, LEX, rep)
    assert first == second
    assert rec.digest() == rep.digest()
    assert len(live.prompts) == 1


def test_record_mode_answers_a_hit_from_the_cache(tmp_path: Path) -> None:
    live = FakeProvider(_ans(effect=None))
    rec = RecordReplayProvider(tmp_path / "c.jsonl", model_id="fake-model",
                               mode="record", provider=live)
    propose_intent(TASK, LEX, rec)
    propose_intent(TASK, LEX, rec)
    assert len(live.prompts) == 1


def test_replay_miss_raises_instead_of_going_live(tmp_path: Path) -> None:
    rep = RecordReplayProvider(tmp_path / "empty.jsonl",
                               model_id="fake-model", mode="replay")
    with pytest.raises(ReplayMiss):
        propose_intent(TASK, LEX, rep)
    with pytest.raises(ReplayMiss):
        propose_derivations(TASK, {"date": "2024-04-03"}, rep, ["x"])


def test_cache_from_another_model_is_refused(tmp_path: Path) -> None:
    cache = tmp_path / "c.jsonl"
    RecordReplayProvider(cache, model_id="fake-model", mode="record",
                         provider=FakeProvider("{}")).complete("p")
    with pytest.raises(ValueError, match="pinned"):
        RecordReplayProvider(cache, model_id="other-model", mode="replay")


def test_provider_must_be_the_pinned_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pinned"):
        RecordReplayProvider(tmp_path / "c.jsonl", model_id="other-model",
                             mode="record", provider=FakeProvider("{}"))


def test_record_mode_requires_a_provider(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        RecordReplayProvider(tmp_path / "c.jsonl", model_id="m", mode="record")
    with pytest.raises(ValueError):
        RecordReplayProvider(tmp_path / "c.jsonl", model_id="m", mode="live")


def test_prompt_hash_is_stable() -> None:
    assert prompt_sha256(INTENT_PROMPT_TEMPLATE) == hashlib.sha256(
        INTENT_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()


# ── derivation proposals: shape only, verification happens downstream ─────

def test_derivation_proposals_keep_only_well_shaped_receipts() -> None:
    raw = json.dumps([
        {"argument": "date", "value": "2024-04-03",
         "transform": "en_date_to_iso", "source_span": "April 3rd, 2024"},
        {"argument": "not_an_arg", "value": 1, "transform": "x",
         "source_span": "y"},
        {"argument": "date", "transform": "x", "source_span": "y"},
        "garbage",
    ])
    out = propose_derivations("on April 3rd, 2024", {"date": "2024-04-03"},
                              FakeProvider(raw), ["en_date_to_iso"])
    assert out == ({"argument": "date", "value": "2024-04-03",
                    "transform": "en_date_to_iso",
                    "source_span": "April 3rd, 2024", "params": {}},)


@pytest.mark.parametrize("response", ["nope", "{}", RuntimeError("boom")])
def test_unusable_derivation_answers_yield_no_receipts(response) -> None:
    assert propose_derivations("t", {"a": 1}, FakeProvider(response), []) == ()


# ── the combination rule and its monotonicity ──────────────────────────────

def _intent(resource: str, effect: str) -> TaskIntent:
    return TaskIntent(operation=effect, resource_type=resource,
                      requested_effect=effect)


def test_combine_fills_a_hole() -> None:
    p = _intent("bus", "read")
    assert combine_intents(None, p) is p


def test_combine_keeps_deterministic_when_proposer_is_silent_or_agrees() -> None:
    d = _intent("bus", "read")
    assert combine_intents(d, None) is d
    assert combine_intents(d, _intent("Bus", "search")) is d


def test_combine_vetoes_on_disagreement() -> None:
    d = _intent("bus", "read")
    assert combine_intents(d, _intent("hotel", "read")) is None
    assert combine_intents(d, _intent("bus", "cancel")) is None


def test_read_family_effects_agree() -> None:
    assert intents_agree(_intent("bus", "get"), _intent("bus", "list"))
    assert not intents_agree(_intent("bus", "get"), _intent("bus", "delete"))


_TOOLS = ["Buses_3_FindBus", "Hotels_2_BookHouse", "Flights_4_SearchFlight",
          "cancel_booking", "get_booking", "Events_3_BuyEventTickets"]
_WORDS = ["find", "book", "search", "cancel", "get", "buy", "show", "delete",
          "a", "bus", "house", "flight", "booking", "event", "tickets",
          "not", "before", "the", "please"]
_EFFECTS = ["read", "create", "cancel", "delete", "update", "search"]
_RES = ["bus", "house", "flight", "booking", "event tickets", "tickets"]


@st.composite
def _case(draw):
    words = draw(st.lists(st.sampled_from(_WORDS), min_size=3, max_size=10))
    task = " ".join(words)

    def intent() -> TaskIntent | None:
        if draw(st.booleans()):
            return None
        span_a = " ".join(draw(st.lists(st.sampled_from(words), min_size=1,
                                        max_size=3)))
        span_r = " ".join(draw(st.lists(st.sampled_from(words), min_size=1,
                                        max_size=3)))
        eff = draw(st.sampled_from(_EFFECTS))
        return TaskIntent(operation=eff, resource_type=draw(
            st.sampled_from(_RES)), requested_effect=eff,
            source_spans=(span_r,), action_spans=(span_a,),
            resource_spans=(span_r,))

    return task, draw(st.sampled_from(_TOOLS)), intent(), intent()


@settings(max_examples=400, deadline=None)
@given(_case())
def test_combined_verdict_is_deterministic_verdict_or_unknown(case) -> None:
    task, tool, det, prop = case
    contract = author_contract(tool)

    def verdict(intent):
        return match_tool_to_intent(contract=contract, intent=intent,
                                    proposed_args={}, task_text=task).verdict

    combined = verdict(combine_intents(det, prop))
    if det is not None:
        assert combined in (verdict(det), GoalMatch.UNKNOWN)
        # The proposer can never manufacture SUPPORTED on a grounded task.
        if verdict(det) is not GoalMatch.SUPPORTED:
            assert combined is not GoalMatch.SUPPORTED


# ── end to end on the spent C-ext3 episodes, against a steered proposer ────

_CEXT3 = (Path(__file__).resolve().parents[1] / "data"
          / "routing_bench_bfcl_v4_cext3")


@pytest.mark.skipif(not (_CEXT3 / "bfcl_holdout.jsonl").exists(),
                    reason="C-ext3 episodes not present")
def test_steered_proposer_adds_no_accept_on_grounded_tasks() -> None:
    """The strongest adversary sees the proposed tool and proposes exactly
    its resource and effect. On every task the deterministic extractor
    grounds, arm F with the combined intent still never ACCEPTs a call that
    arm F alone did not ACCEPT. (Spent set: a regression guard on the rule,
    not a measurement.)"""
    from remora.policy.decision_engine import RemoraDecisionEngine
    from remora.policy.report import DecisionAction
    from remora.toolcall.routing.bfcl_semantic_bundle import (
        author_bundle,
        extract_intent,
        full_resource_set,
        resource_lexicon,
    )
    from remora.toolcall.routing.compatibility import StateIndex
    from remora.toolcall.routing.episode import RoutingEpisode
    from remora.toolcall.routing.evaluate import build_full_observation
    from remora.toolcall.routing.tool_registry import ToolRegistry

    episodes = [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in (_CEXT3 / "bfcl_holdout.jsonl")
        .read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    registry = ToolRegistry.from_json_dict(json.loads(
        (_CEXT3 / "registry.json").read_text(encoding="utf-8")))
    tools = sorted({e.proposed_tool_name for e in episodes
                    if e.proposed_tool_name})
    bundle = author_bundle(tools)
    lexicon = resource_lexicon(bundle, tools)
    full = full_resource_set(bundle, tools)
    state = StateIndex.from_values(set(), scopes=())
    engine = RemoraDecisionEngine(low_consequence_accept=True,
                                  semantic_authority_floor=True)

    grounded = 0
    for e in episodes:
        det = extract_intent(e.user_task or "", lexicon, full)
        if det is None:
            continue
        grounded += 1
        contract = bundle.get(e.proposed_tool_name or "")
        steered = None if contract is None else TaskIntent(
            operation=contract.effect, resource_type=contract.resource_type,
            requested_effect=contract.effect,
            source_spans=det.source_spans, action_spans=det.action_spans,
            resource_spans=det.resource_spans, proposed_by="steered")
        base = engine.decide(build_full_observation(
            e, registry, state, contracts=bundle, intent=det)).action
        comb = engine.decide(build_full_observation(
            e, registry, state, contracts=bundle,
            intent=combine_intents(det, steered))).action
        if comb is DecisionAction.ACCEPT:
            assert base is DecisionAction.ACCEPT, e.id
    assert grounded == 1793
