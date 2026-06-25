# Author: Stian Skogbrott
# License: Apache-2.0
"""Train GainabilityClassifier on full_coverage_bound items and report lift.

Lift = (gainable items routed correctly) - (already-correct items mis-routed).
A positive lift means the classifier is net-beneficial as a routing aid.

Schema adaptation
-----------------
The plan's assumed schema places per-item records directly under ``items`` /
``results`` with ``majority_correct`` and ``alternative_branches`` fields.
The actual ``results/full_coverage_bound_results.json`` is a summary file
(no per-item records). Its ``meta.ablation_source`` points at
``results/ablation_v2_canonical_results.json`` which contains per-condition
``items`` arrays. We:
  - if the input is the summary file, transparently resolve and load the
    ablation source instead;
  - normalise the conditions-keyed layout into a flat list of per-item dicts,
    one per ``item_id``, with ``majority_correct`` (from ``B_majority``) and
    ``alternative_branches`` (each other condition's per-item correctness).

This keeps ``_label_gainable`` working against the plan's exact field names
without fabricating any label.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from remora.selective.gainability import GainabilityClassifier, extract_features
from remora.selective.feature_join import (
    load_joined_items,
    build_gainability_features,
    gainability_label,
    feature_coverage_report,
)


MAJORITY_CONDITION = "B_majority"


def _label_gainable(item: dict) -> bool:
    """An item is gainable if majority is wrong and some alternative is right."""
    if item.get("majority_correct") is True:
        return False
    alts = item.get("alternative_branches") or item.get("alternatives") or []
    for branch in alts:
        if branch.get("correct") is True:
            return True
    return False


def _load_items(input_path: Path) -> list[dict]:
    """Load per-item records, resolving summary -> ablation source if needed."""
    raw = json.loads(input_path.read_text(encoding="utf-8"))

    # Plan's expected layout: top-level list or items/results key.
    items = None
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        if isinstance(raw.get("items"), list):
            items = raw["items"]
        elif isinstance(raw.get("results"), list):
            items = raw["results"]

    if items is not None and items and isinstance(items[0], dict) and (
        "majority_correct" in items[0]
        or "alternative_branches" in items[0]
        or "alternatives" in items[0]
    ):
        return items

    # Defensive adaptation: summary file with ablation_source pointing at
    # a conditions-keyed per-item layout.
    if isinstance(raw, dict) and "conditions" in raw and isinstance(raw["conditions"], dict):
        return _normalise_conditions_layout(raw["conditions"])

    if isinstance(raw, dict):
        src = (raw.get("meta") or {}).get("ablation_source")
        if src:
            src_path = (input_path.parent / Path(src).name)
            if not src_path.exists():
                # Fall back to repo-rooted path as given in the JSON.
                src_path = Path(src)
            if src_path.exists():
                src_raw = json.loads(src_path.read_text(encoding="utf-8"))
                if isinstance(src_raw, dict) and "conditions" in src_raw:
                    return _normalise_conditions_layout(src_raw["conditions"])

    raise SystemExit(
        f"Unrecognised structure in {input_path}: expected per-item records "
        "with majority_correct / alternative_branches, or a conditions-keyed "
        "layout (with B_majority + other conditions)."
    )


def _normalise_conditions_layout(conditions: dict) -> list[dict]:
    """Flatten a conditions->items layout into per-item dicts with the
    plan's expected fields (majority_correct, alternative_branches)."""
    if MAJORITY_CONDITION not in conditions:
        raise SystemExit(
            f"Conditions layout missing '{MAJORITY_CONDITION}'; "
            f"got {list(conditions.keys())}."
        )
    maj_items = conditions[MAJORITY_CONDITION].get("items") or []
    other_names = [c for c in conditions if c != MAJORITY_CONDITION]

    # Index every condition's items by item_id for O(1) lookup.
    indexed: dict[str, dict[str, dict]] = {name: {} for name in conditions}
    for name, payload in conditions.items():
        for it in payload.get("items") or []:
            iid = it.get("item_id")
            if iid is None:
                continue
            indexed[name][iid] = it

    flat: list[dict] = []
    for maj in maj_items:
        iid = maj.get("item_id")
        if iid is None:
            continue
        # Build observable features carried through to extract_features.
        # The canonical schema lacks REMORA observables per-item; we surface
        # what is available so extract_features can lift them into the vector.
        flat.append(
            {
                "item_id": iid,
                "majority_correct": bool(maj.get("correct", False)),
                "alternative_branches": [
                    {
                        "condition": name,
                        "correct": bool(indexed[name].get(iid, {}).get("correct", False)),
                    }
                    for name in other_names
                    if iid in indexed[name]
                ],
                # Lifted observables for extract_features; missing keys default
                # to 0 inside extract_features.
                "trust_score": _safe_float(maj.get("final_V"), default=0.0),
                "order_parameter": 0.0,
                "susceptibility": _safe_float(
                    indexed.get("C_remora", {}).get(iid, {}).get("final_V"), default=0.0
                ),
                "hallucination_bound": 0.0,
                "dissensus": _safe_float(
                    indexed.get("D1_strict", {}).get(iid, {}).get("final_V"), default=0.0
                ),
                "rho_response_agreement": float(
                    sum(
                        1
                        for n in other_names
                        if indexed[n].get(iid, {}).get("correct", False)
                    )
                ) / max(1, len(other_names)),
                "phase": "critical" if maj.get("is_adversarial") else "ordered",
            }
        )
    return flat


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _train_test_split(items: list[dict], frac: float, seed: int) -> tuple[list[dict], list[dict]]:
    idx = list(range(len(items)))
    random.Random(seed).shuffle(idx)
    cut = int(round(len(items) * frac))
    return [items[i] for i in idx[:cut]], [items[i] for i in idx[cut:]]


def _run_v2(output: Path, train_frac: float = 0.8, seed: int = 0) -> None:
    """V2 routing experiment using joined thermodynamic + ablation features."""
    items = load_joined_items()
    if not items:
        raise SystemExit("load_joined_items() returned empty list")

    train, test = _train_test_split(items, train_frac, seed)

    X_train = [build_gainability_features(it) for it in train]
    y_train = [gainability_label(it) for it in train]

    n_gainable_train = sum(1 for y in y_train if y)
    class_imbalance_ratio = (
        n_gainable_train / (len(y_train) - n_gainable_train)
        if (len(y_train) - n_gainable_train) > 0
        else float("inf")
    )

    if not any(y_train):
        payload = {
            "n_train": len(train),
            "n_test": len(test),
            "n_gainable_train": 0,
            "n_gainable_test": 0,
            "precision": 0.0,
            "recall": 0.0,
            "net_lift": 0,
            "class_imbalance_ratio": 0.0,
            "feature_coverage": feature_coverage_report(items),
            "conclusion": "not_demonstrated — no gainable items in training split",
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {output}: no gainable items in training split")
        return

    clf = GainabilityClassifier()
    clf.fit(X_train, y_train)

    # Evaluate on held-out test split.
    X_test = [build_gainability_features(it) for it in test]
    y_test = [gainability_label(it) for it in test]
    n_gainable_test = sum(1 for y in y_test if y)

    tp = fp = tn = fn = 0
    routed_gain = 0
    misrouted_correct = 0
    for it, feats, truly_gainable in zip(test, X_test, y_test):
        pred = clf.predict_proba(feats) >= 0.5
        if pred and truly_gainable:
            tp += 1
            routed_gain += 1
        elif pred and not truly_gainable:
            fp += 1
            if it.get("majority_correct") is True:
                misrouted_correct += 1
        elif not pred and truly_gainable:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    net_lift = routed_gain - misrouted_correct

    if net_lift <= 0:
        conclusion = "not_demonstrated — class imbalance prevents discrimination"
    else:
        conclusion = f"lift_demonstrated — net_lift={net_lift}"

    cov_report = feature_coverage_report(items)

    payload = {
        "n_train": len(train),
        "n_test": len(test),
        "n_gainable_train": n_gainable_train,
        "n_gainable_test": n_gainable_test,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "precision": precision,
        "recall": recall,
        "net_lift": float(net_lift),
        "class_imbalance_ratio": class_imbalance_ratio,
        "feature_coverage": cov_report,
        "conclusion": conclusion,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"wrote {output}: precision={precision:.3f} recall={recall:.3f} "
        f"net_lift={net_lift} conclusion={conclusion!r}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="results/full_coverage_bound_results.json", type=Path)
    parser.add_argument("--output", default="results/gainability_routing.json", type=Path)
    parser.add_argument("--train-frac", type=float, default=0.6)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--v2",
        action="store_true",
        default=False,
        help="Use joined thermodynamic+ablation features (writes gainability_routing_v2.json)",
    )
    args = parser.parse_args()

    if args.v2:
        v2_output = args.output.parent / "gainability_routing_v2.json"
        _run_v2(output=v2_output, train_frac=0.8, seed=args.seed)
        return

    items = _load_items(args.input)
    if not items:
        raise SystemExit(f"No items loaded from {args.input}")

    train, test = _train_test_split(items, args.train_frac, args.seed)
    X_train = [extract_features(it) for it in train]
    y_train = [_label_gainable(it) for it in train]
    if not any(y_train):
        raise SystemExit("No gainable items in training split — increase --train-frac or seed.")

    clf = GainabilityClassifier()
    clf.fit(X_train, y_train)

    # Evaluate on held-out test split.
    tp = fp = tn = fn = 0
    routed_gain = 0
    misrouted_correct = 0
    for it in test:
        feats = extract_features(it)
        pred = clf.predict_proba(feats) >= 0.5
        truly_gainable = _label_gainable(it)
        if pred and truly_gainable:
            tp += 1
            routed_gain += 1
        elif pred and not truly_gainable:
            fp += 1
            if it.get("majority_correct") is True:
                misrouted_correct += 1
        elif not pred and truly_gainable:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    payload = {
        "input": args.input.as_posix(),
        "n_train": len(train),
        "n_test": len(test),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "precision": precision,
        "recall": recall,
        "routed_gainable_items": routed_gain,
        "misrouted_already_correct_items": misrouted_correct,
        "net_lift": routed_gain - misrouted_correct,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {args.output}: precision={precision:.3f} recall={recall:.3f} net_lift={payload['net_lift']}")


if __name__ == "__main__":
    main()
