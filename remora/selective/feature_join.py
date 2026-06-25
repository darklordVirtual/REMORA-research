"""Join per-item data from multiple result artifacts to build richer feature vectors.

Used by gainability experiments to improve feature coverage.
"""
from __future__ import annotations

import json
from pathlib import Path

ABLATION_PATH = Path("results/ablation_v2_canonical_results.json")
THERMO_PATH = Path("results/thermodynamic_eval_results.json")

MAJORITY_CONDITION = "B_majority"


def load_joined_items(
    ablation_path: Path = ABLATION_PATH,
    thermo_path: Path = THERMO_PATH,
) -> list[dict]:
    """Join ablation and thermodynamic eval items by item_id or question text.

    Strategy:
    1. Load ablation items (each has: item_id, question, majority_correct,
       d2_correct, d2_routed, helped_vs_majority, hurt_vs_majority,
       benchmark, domain, is_adversarial, difficulty)
    2. Load thermo items (each has: item_id, temperature, trust_score,
       order_parameter, susceptibility, hallucination_bound, phase, ...)
    3. Join on item_id (exact match). If item_id not present, try joining on
       question text (exact string match).
    4. For items with no thermo match, thermo fields remain None.
    5. Return merged list with all fields from both artifacts.
    """
    # -- Load ablation items --
    ablation_raw = json.loads(ablation_path.read_text(encoding="utf-8"))
    ablation_items = _extract_ablation_items(ablation_raw)

    # -- Load thermo items --
    thermo_raw = json.loads(thermo_path.read_text(encoding="utf-8"))
    thermo_items_raw = thermo_raw.get("items", []) if isinstance(thermo_raw, dict) else []

    # Index thermo items by item_id and by question text for fallback join.
    thermo_by_id: dict[str, dict] = {}
    thermo_by_question: dict[str, dict] = {}
    for t in thermo_items_raw:
        if isinstance(t, dict):
            tid = t.get("item_id")
            if tid:
                thermo_by_id[str(tid)] = t
            q = t.get("question")
            if q:
                thermo_by_question[str(q)] = t

    # -- Merge --
    merged: list[dict] = []
    for abl in ablation_items:
        result = dict(abl)  # copy all ablation fields

        # Try join by item_id first.
        t_match: dict | None = None
        abl_id = abl.get("item_id")
        if abl_id is not None:
            t_match = thermo_by_id.get(str(abl_id))

        # Fallback: join by question text.
        if t_match is None:
            q = abl.get("question")
            if q:
                t_match = thermo_by_question.get(str(q))

        # Merge thermo fields (None if no match).
        _THERMO_FIELDS = (
            "trust_score",
            "order_parameter",
            "susceptibility",
            "hallucination_bound",
            "phase",
            "temperature",
            "action",
            "d2_correct",
            "d2_routed",
            "helped_vs_majority",
            "hurt_vs_majority",
        )
        if t_match is not None:
            for fld in _THERMO_FIELDS:
                # Thermo fields take precedence over ablation placeholders.
                if fld in t_match:
                    result[fld] = t_match[fld]
            # Also bring over any fields not already in result.
            for k, v in t_match.items():
                if k not in result:
                    result[k] = v
        else:
            # Ensure thermo fields are explicitly None when there is no match.
            for fld in _THERMO_FIELDS:
                if fld not in result:
                    result[fld] = None

        merged.append(result)

    return merged


def _extract_ablation_items(raw: object) -> list[dict]:
    """Extract a flat list of per-item dicts from the ablation artifact."""
    if isinstance(raw, list):
        return raw

    if not isinstance(raw, dict):
        return []

    # Direct items / results key.
    for key in ("items", "results"):
        val = raw.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            if "majority_correct" in val[0] or "correct" in val[0]:
                return val

    # Conditions-keyed layout — flatten majority condition items.
    conditions = raw.get("conditions")
    if isinstance(conditions, dict) and MAJORITY_CONDITION in conditions:
        return _flatten_conditions(conditions)

    return []


def _flatten_conditions(conditions: dict) -> list[dict]:
    """Flatten conditions dict into per-item dicts using B_majority as base."""
    maj_items = conditions[MAJORITY_CONDITION].get("items") or []
    _other_names = [c for c in conditions if c != MAJORITY_CONDITION]  # noqa: F841

    indexed: dict[str, dict[str, dict]] = {n: {} for n in conditions}
    for name, payload in conditions.items():
        for it in payload.get("items") or []:
            if isinstance(it, dict):
                iid = it.get("item_id")
                if iid is not None:
                    indexed[name][str(iid)] = it

    flat: list[dict] = []
    for maj in maj_items:
        if not isinstance(maj, dict):
            continue
        iid = maj.get("item_id")
        if iid is None:
            continue
        siid = str(iid)

        majority_correct = bool(maj.get("correct", False))

        # d2_correct: True if C_remora condition exists and was correct.
        d2_item = indexed.get("C_remora", {}).get(siid, {})
        d2_correct = bool(d2_item.get("correct", False)) if d2_item else False

        flat.append(
            {
                "item_id": iid,
                "majority_correct": majority_correct,
                "d2_correct": d2_correct,
                "d2_routed": bool(d2_item.get("routed", False)) if d2_item else False,
                "benchmark": maj.get("benchmark"),
                "domain": maj.get("domain"),
                "is_adversarial": bool(maj.get("is_adversarial", False)),
                "difficulty": maj.get("difficulty"),
                "helped_vs_majority": None,
                "hurt_vs_majority": None,
                # Thermo fields default to None; filled in by join.
                "trust_score": None,
                "order_parameter": None,
                "susceptibility": None,
                "hallucination_bound": None,
                "phase": None,
                "temperature": None,
            }
        )
    return flat


def build_gainability_features(item: dict) -> list[float]:
    """Richer feature vector for gainability classification.

    Features (fixed order — load-bearing):
    0: trust_score (default 0.0)
    1: order_parameter (default 0.0)
    2: susceptibility (default 0.0)
    3: hallucination_bound (default 0.0)
    4: dissensus: 1.0 - trust_score as proxy if no direct field
    5: phase_ordered: 1.0 if phase=="ordered" else 0.0
    6: phase_critical: 1.0 if phase=="critical" else 0.0
    7: phase_disordered: 1.0 if phase=="disordered" else 0.0
    8: temperature (default 0.0 if missing)
    9: is_adversarial: 1.0 if item.get("is_adversarial") else 0.0
    10: difficulty_hard: 1.0 if item.get("difficulty") == "hard" else 0.0
    """

    def _f(key: str, default: float = 0.0) -> float:
        v = item.get(key)
        if v is None:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    trust_score = _f("trust_score")
    order_parameter = _f("order_parameter")
    susceptibility = _f("susceptibility")
    hallucination_bound = _f("hallucination_bound")

    # dissensus: prefer explicit field; fall back to 1 - trust_score proxy.
    if item.get("dissensus") is not None:
        dissensus = _f("dissensus")
    else:
        dissensus = 1.0 - trust_score

    phase = str(item.get("phase") or "").lower()
    phase_ordered = 1.0 if phase == "ordered" else 0.0
    phase_critical = 1.0 if phase == "critical" else 0.0
    phase_disordered = 1.0 if phase == "disordered" else 0.0

    temperature = _f("temperature")
    is_adversarial = 1.0 if item.get("is_adversarial") else 0.0
    difficulty_hard = 1.0 if item.get("difficulty") == "hard" else 0.0

    return [
        trust_score,
        order_parameter,
        susceptibility,
        hallucination_bound,
        dissensus,
        phase_ordered,
        phase_critical,
        phase_disordered,
        temperature,
        is_adversarial,
        difficulty_hard,
    ]


def gainability_label(item: dict) -> bool:
    """Target: majority was wrong AND some alternative branch was right.

    Logic: item["majority_correct"] == False AND item.get("d2_correct") == True
    (same as existing GainabilityClassifier semantics)
    """
    return not item.get("majority_correct", True) and bool(item.get("d2_correct", False))


def feature_coverage_report(items: list[dict]) -> dict:
    """Return dict with coverage stats: how many items have each key non-None."""
    if not items:
        return {}

    # Collect all keys across all items.
    all_keys: set[str] = set()
    for it in items:
        all_keys.update(it.keys())

    report: dict[str, dict] = {}
    n = len(items)
    for key in sorted(all_keys):
        count = sum(1 for it in items if it.get(key) is not None)
        report[key] = {
            "count": count,
            "total": n,
            "coverage_pct": round(100.0 * count / n, 2) if n else 0.0,
        }
    return report
