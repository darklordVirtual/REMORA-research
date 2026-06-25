from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from remora.toolcall.schema import ToolCallTask


BLIND_FAMILIES = frozenset({
    "safe_looking_dangerous",
    "production_target_ambiguity",
    "regulated_ambiguity",
    "counterfactual_trap",
    "prompt_injection",
})


def split_tasks_v2(tasks: list[ToolCallTask]) -> dict[str, list[ToolCallTask]]:
    """Deterministic family-aware split.

    - blind: all tasks from held-out families (OOD by scenario family)
    - calibration / validation: remaining tasks split 60/40 by stable hash

    This yields ~30/20/50 when family counts are balanced.
    """
    by_family: dict[str, list[ToolCallTask]] = defaultdict(list)
    for task in tasks:
        family = str((task.context or {}).get("scenario_family", "unknown"))
        by_family[family].append(task)

    blind: list[ToolCallTask] = []
    remainder: list[ToolCallTask] = []
    for family, items in by_family.items():
        if family in BLIND_FAMILIES:
            blind.extend(items)
        else:
            remainder.extend(items)

    remainder_sorted = sorted(remainder, key=lambda t: sha256(t.task_id.encode("utf-8")).hexdigest())
    n_cal = int(0.60 * len(remainder_sorted))
    calibration = remainder_sorted[:n_cal]
    validation = remainder_sorted[n_cal:]

    return {
        "calibration": calibration,
        "validation": validation,
        "blind_test": sorted(blind, key=lambda t: t.task_id),
    }
