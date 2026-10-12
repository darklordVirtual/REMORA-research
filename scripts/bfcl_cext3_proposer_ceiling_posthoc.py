#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""POST-HOC / DEVELOPMENT ONLY: where C-ext3 autonomy is lost, and how much
an intent proposer could recover at most (QV2-06 slice 1).

Replays arm F (frozen bundle, semantic-authority floor, empty state index) at
the current commit on the SPENT C-ext3 episodes. NOT CONFIRMATORY: the set was
evaluated once on 2026-08-19 and every number here was seen while designing
``intent_proposer``. Nothing this script writes may be cited as a result
(docs/05-claim-hygiene.md). It exists to decide what SAP v6 should
pre-register, and to make the counts in NEGATIVE_RESULTS.md §39's development
notes reproducible.

Three questions:

1. Gate ordering: which reason stops each obtainable-argument episode that
   does not route VERIFY?
2. Ceiling of the fill-and-veto rule: if a proposer vetoed every
   extractor refutation, how many obtainable episodes would route VERIFY and
   how many gold reads would ACCEPT?
3. Ceiling of any proposer held to the verbatim discipline: an "aimed"
   proposal names the proposed tool's own resource and effect, quoted from
   the task, and must pass ``parse_intent_proposal``. On gold reads that is
   an oracle; on wrong calls it is the strongest steered adversary. The
   aimed proposal REPLACES the extractor's intent (override mode), which the
   shipped rule never does, so this bounds both gain and exposure.

Writes artifacts/posthoc/bfcl_cext3_proposer_ceiling.json with
status=post_hoc_development_only.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.toolcall.routing.bfcl_semantic_bundle import (  # noqa: E402
    author_bundle,
    extract_intent,
    full_resource_set,
    resource_lexicon,
)
from remora.toolcall.routing.compatibility import StateIndex  # noqa: E402
from remora.toolcall.routing.episode import RoutingEpisode  # noqa: E402
from remora.toolcall.routing.evaluate import (  # noqa: E402
    _ACTION_TO_ROUTE,
    build_full_observation,
)
from remora.toolcall.routing.goal_match import EFFECT_VOCABULARY  # noqa: E402
from remora.toolcall.routing.intent_proposer import (  # noqa: E402
    parse_intent_proposal,
)
from remora.toolcall.routing.mutations import (  # noqa: E402
    MutationFamily,
    family_of,
)
from remora.toolcall.routing.tool_registry import ToolRegistry  # noqa: E402

HOLDOUT = REPO_ROOT / "data" / "routing_bench_bfcl_v4_cext3"
OUT = REPO_ROOT / "artifacts" / "posthoc" / "bfcl_cext3_proposer_ceiling.json"


def main() -> int:
    episodes = [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in (HOLDOUT / "bfcl_holdout.jsonl")
        .read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    registry = ToolRegistry.from_json_dict(json.loads(
        (HOLDOUT / "registry.json").read_text(encoding="utf-8")))
    tools = sorted({e.proposed_tool_name for e in episodes
                    if e.proposed_tool_name})
    bundle = author_bundle(tools)
    lexicon = resource_lexicon(bundle, tools)
    full = full_resource_set(bundle, tools)
    state = StateIndex.from_values(set(), scopes=())
    engine = RemoraDecisionEngine(low_consequence_accept=True,
                                  semantic_authority_floor=True)

    def fam(e: RoutingEpisode) -> str:
        return family_of(e) or ("native:" + e.id.rsplit(":", 1)[1])

    def decide(e, intent):
        d = engine.decide(build_full_observation(
            e, registry, state, contracts=bundle, intent=intent))
        return _ACTION_TO_ROUTE[d.action].value, d.reasons[0].value

    def aimed(e):
        contract = bundle.get(e.proposed_tool_name or "")
        task = e.user_task or ""
        if contract is None:
            return None
        low = task.lower()
        names = [n for n in (contract.resource_type, *contract.resource_aliases)
                 if n in lexicon]
        effects = [contract.effect] + (["read"] if contract.is_read else [])
        for name in sorted(names, key=len, reverse=True):
            m = re.search(rf"\b{re.escape(name)}\b", low)
            if not m:
                continue
            for eff in effects:
                for kw in sorted(EFFECT_VOCABULARY.get(eff, ())):
                    k = re.search(rf"\b{re.escape(kw)}\b", low)
                    if not k:
                        continue
                    p = parse_intent_proposal(json.dumps({
                        "effect": eff, "action_span": task[k.start():k.end()],
                        "resource": name,
                        "resource_span": task[m.start():m.end()],
                    }), task, lexicon)
                    if p.intent is not None:
                        return p.intent
        return None

    obtainable_reasons: Counter[str] = Counter()
    read_reasons: Counter[str] = Counter()
    unparseable_reads: Counter[str] = Counter()
    c: Counter[str] = Counter()
    for e in episodes:
        f = fam(e)
        contract = bundle.get(e.proposed_tool_name or "")
        is_wrong = ((e.predicates is not None
                     and e.predicates.call_in_gold_set.value is False)
                    or f == MutationFamily.WRONG_TOOL.value)
        is_read = f == "identity" and contract is not None and contract.is_read
        is_obt = f == MutationFamily.MISSING_ARG_OBTAINABLE.value
        if not (is_wrong or is_read or is_obt):
            continue
        det = extract_intent(e.user_task or "", lexicon, full)
        route, reason = decide(e, det)
        key = "wrong_call" if is_wrong else ("gold_read" if is_read
                                             else "obtainable")
        want = {"wrong_call": "accept", "gold_read": "accept",
                "obtainable": "verify"}[key]
        c[f"{key}.n"] += 1
        c[f"{key}.arm_F.{want}"] += route == want
        c[f"{key}.extractor_grounded_nothing"] += det is None
        if is_obt and route != "verify":
            obtainable_reasons[f"{route}:{reason}"] += 1
        if is_read and route != "accept":
            read_reasons[f"{route}:{reason}"] += 1
        # (2) fill-and-veto ceiling: every refutation vetoed into UNKNOWN.
        vetoed = (decide(e, None)[0]
                  if det is not None and route == "abstain" else route)
        c[f"{key}.veto_ceiling.{want}"] += vetoed == want
        # (3) aimed proposal in override mode.
        a = aimed(e)
        c[f"{key}.aimed_parses"] += a is not None
        c[f"{key}.aimed_override.{want}"] += (
            decide(e, a if a is not None else det)[0] == want)
        if is_read and a is None:
            low = (e.user_task or "").lower()
            names = (contract.resource_type, *contract.resource_aliases)
            res = ("resource_named" if any(
                n in lexicon and re.search(rf"\b{re.escape(n)}\b", low)
                for n in names) else "resource_generic_only" if any(
                re.search(rf"\b{re.escape(n)}\b", low) for n in names)
                else "resource_absent")
            eff = ("read_keyword" if any(
                re.search(rf"\b{re.escape(k)}\b", low)
                for k in EFFECT_VOCABULARY["read"]) else "no_read_keyword")
            unparseable_reads[f"{res}+{eff}"] += 1

    report = {
        "status": "post_hoc_development_only",
        "warning": (
            "Spent C-ext3 set, replayed at the current commit. Not a result; "
            "may not be cited as one. Purpose: SAP v6 design input for QV2-06."
        ),
        "configuration": "arm F: frozen bundle, semantic_authority_floor, "
                         "low_consequence_accept, empty StateIndex",
        "counts": dict(sorted(c.items())),
        "obtainable_not_verify_by_first_reason":
            dict(obtainable_reasons.most_common()),
        "gold_read_not_accept_by_first_reason":
            dict(read_reasons.most_common()),
        "gold_reads_no_aimed_proposal_parses":
            dict(unparseable_reads.most_common()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n")
                    .encode("utf-8"))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
