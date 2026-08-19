#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""POST-HOC / DEVELOPMENT ONLY — BFCL C-ext2 semantic reanalysis (SAP v5 §8).

Re-scores the SPENT C-ext2 substituted episodes under the semantic-authority
mechanism to categorize the 28-accept residue before the C-ext3 freeze.
NOT CONFIRMATORY: the holdout is spent, and the dev contract/intent
heuristics here saw everything. Nothing this script produces may be cited as
a result anywhere (docs/05-claim-hygiene.md); its output is a development
artifact whose only purpose is to inform the frozen contract-bundle and
intent-extractor authoring.

Arms (SAP v5 §5, dev preview):
  A  structural only (the locked C-ext2 configuration — sanity anchor)
  C  + contracts/intent (tool_matches_goal / expected_effect_matches)
  F  + semantic-authority UNKNOWN floor

Writes artifacts/posthoc/bfcl_cext2_semantic_reanalysis.json with
status=post_hoc_development_only.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.toolcall.routing.compatibility import StateIndex  # noqa: E402
from remora.toolcall.routing.episode import RoutingEpisode  # noqa: E402
from remora.toolcall.routing.evaluate import (  # noqa: E402
    _ACTION_TO_ROUTE,
    build_full_observation,
)
from remora.toolcall.routing.goal_match import (  # noqa: E402
    match_tool_to_intent,
)
from remora.toolcall.routing.tool_registry import ToolRegistry  # noqa: E402

HOLDOUT = REPO_ROOT / "data" / "routing_bench_bfcl_v4"
OUT = REPO_ROOT / "artifacts" / "posthoc" / "bfcl_cext2_semantic_reanalysis.json"

from remora.toolcall.routing.bfcl_semantic_bundle import (  # noqa: E402
    author_bundle,
    extract_intent,
    full_resource_set,
    resource_lexicon,
)


def main() -> int:
    episodes = [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in (HOLDOUT / "bfcl_holdout.jsonl")
        .read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    registry = ToolRegistry.from_json_dict(
        json.loads((HOLDOUT / "registry.json").read_text(encoding="utf-8"))
    )
    subs = [
        e for e in episodes
        if e.predicates is not None
        and e.predicates.call_in_gold_set.value is False
    ]
    all_tools = sorted({e.proposed_tool_name for e in subs if e.proposed_tool_name})
    contracts = author_bundle(all_tools)
    lexicon = resource_lexicon(contracts, all_tools)
    full = full_resource_set(contracts, all_tools)

    state = StateIndex.from_values(set(), scopes=())
    engines = {
        "A_structural": RemoraDecisionEngine(low_consequence_accept=True),
        "C_contracts_intent": RemoraDecisionEngine(low_consequence_accept=True),
        "F_unknown_floor": RemoraDecisionEngine(
            low_consequence_accept=True, semantic_authority_floor=True
        ),
    }

    per_arm: dict[str, Counter] = {a: Counter() for a in engines}
    residue: list[dict] = []
    for e in subs:
        intent = extract_intent(e.user_task or "", lexicon, full)
        for arm, engine in engines.items():
            if arm == "A_structural":
                obs = build_full_observation(e, registry, state)
            else:
                obs = build_full_observation(
                    e, registry, state, contracts=contracts, intent=intent
                )
            route = _ACTION_TO_ROUTE[engine.decide(obs).action]
            per_arm[arm][route.value] += 1
            if arm == "F_unknown_floor" and route.value == "accept":
                match = match_tool_to_intent(
                    contract=contracts.get(e.proposed_tool_name or ""),
                    intent=intent,
                    proposed_args=e.proposed_tool_args,
                    task_text=e.user_task,
                )
                residue.append({
                    "id": e.id,
                    "tool": e.proposed_tool_name,
                    "goal_match": match.verdict.value,
                    "reason": match.reason,
                })

    report = {
        "status": "post_hoc_development_only",
        "warning": ("NOT CONFIRMATORY. Spent C-ext2 data, dev heuristics that "
                    "saw everything. Never cite as a result "
                    "(docs/05-claim-hygiene.md; SAP v5 section 8)."),
        "n_substituted": len(subs),
        "n_dev_contracts": len(all_tools),
        "n_intents_extracted": sum(
            1 for e in subs
            if extract_intent(e.user_task or "", lexicon, full)
        ),
        "per_arm_routes": {a: dict(c) for a, c in per_arm.items()},
        "arm_F_residual_accepts": residue,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"POST-HOC (dev only) — substituted episodes: {len(subs)}")
    for arm, counts in per_arm.items():
        print(f"  {arm:22} {dict(counts)}")
    print(f"  arm F residual accepts: {len(residue)}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
