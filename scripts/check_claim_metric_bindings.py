# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every published number in an active claim must resolve to its artifact.

RMR-007. The existing claim gates verify shape: that the register parses, that
anchors line up, that artifact paths exist and that their hashes are fresh.
CLAIM-007 passed all of them for weeks while stating a false-accept rate of
30% and citing a file that records 1.43%, because no gate ever opened the
artifact and looked for the number.

This gate does exactly that, and nothing more. For each active claim with a
``metrics`` block, every numeric metric must be one of:

``path``
    a pointer of the form ``<artifact>#<dotted.json.path>`` whose value equals
    the claimed number, optionally after a stated ``scale`` and a stated
    ``rounded_to`` (the number of decimals the claim publishes). This is the
    strong form: the number is in the file.

    Equality alone is weak: a binding that hits the right number at the wrong
    path passes it, and a coincidence is not provenance. Two further rules
    close that gap, both fail-closed. No two metrics of one claim may name the
    same artifact path, because one path cannot be the evidence for two
    different quantities. And the end of the path must share a word with the
    metric it stands for, unless the binding carries a ``path_rationale``
    saying in words why the mismatched name is nevertheless the right field.

``derived``
    ``wilson_upper(<k path>, <n path>)``, recomputed here and compared. Written
    by hand, never guessed: a brute-force search over an artifact's numbers
    finds coincidental pairs that produce the right value from the wrong
    quantities, and a coincidence is not provenance.

``unbound``
    an explicit reason why the number is not in the artifact. Declaring it is
    not a pass: the total is counted against a baseline that may only fall, so
    the debt is visible and cannot grow quietly.

A metric that is none of these fails the gate.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = REPO_ROOT / "docs" / "assurance" / "claim_register_v1.yaml"
BASELINE_PATH = REPO_ROOT / "docs" / "assurance" / "claim_metric_binding_baseline.json"

TOLERANCE = 5e-3

_DERIVED = re.compile(r"^wilson_upper\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)$")

# Words that carry no evidence about *which* quantity a field holds. Dropping
# them stops "value", "n" or "pct" from matching everything.
_GENERIC_TOKENS = frozenset({"pct", "n", "d", "value", "count", "total", "num"})


def tokens(name: str) -> set[str]:
    """Lowercase word tokens of an identifier, minus the generic ones."""

    return {
        part
        for part in re.split(r"[^0-9a-zA-Z]+", name.lower())
        if part and part not in _GENERIC_TOKENS
    }


def path_names_the_metric(metric: str, pointer: str) -> bool:
    """Does the end of ``pointer`` share a word with the metric name?

    Only the last two segments are considered: the leaf holds the quantity and
    its parent holds the thing measured, which is where a name like
    ``targets.known_wrong_call_accept.value`` carries its meaning.
    """

    path = pointer.split("#", 1)[-1]
    segments = [part for part in path.strip().split(".") if part]
    tail = set()
    for segment in segments[-2:]:
        tail |= tokens(segment)
    return bool(tokens(metric) & tail)


class BindingError(Exception):
    """A metric could not be resolved as declared."""


def wilson_upper(k: float, n: float, z: float = 1.96) -> float:
    """Upper bound of the 95% Wilson interval, as a fraction."""

    if n <= 0:
        return 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    spread = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return min(1.0, centre + spread)


def load_artifact(cache: dict[str, Any], relative: str) -> Any:
    if relative not in cache:
        path = REPO_ROOT / relative
        if not path.exists():
            raise BindingError(f"artifact {relative} does not exist")
        if path.suffix != ".json":
            raise BindingError(f"artifact {relative} is not JSON and cannot be pointed into")
        cache[relative] = json.loads(path.read_text(encoding="utf-8"))
    return cache[relative]


def resolve_pointer(cache: dict[str, Any], pointer: str) -> float:
    """Resolve ``<artifact>#<dotted.path>`` to a number."""

    if "#" not in pointer:
        raise BindingError(f"pointer {pointer!r} is missing its '#<path>' half")
    relative, path = pointer.split("#", 1)
    node: Any = load_artifact(cache, relative.strip())
    for part in path.strip().split("."):
        if not part:
            continue
        index = None
        if part.endswith("]") and "[" in part:
            part, raw_index = part[:-1].split("[", 1)
            index = int(raw_index)
        if part:
            if not isinstance(node, dict) or part not in node:
                raise BindingError(f"{relative}: no key {part!r} on the way to {path!r}")
            node = node[part]
        if index is not None:
            if not isinstance(node, list) or index >= len(node):
                raise BindingError(f"{relative}: index [{index}] out of range in {path!r}")
            node = node[index]
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        raise BindingError(f"{pointer}: resolves to {node!r}, which is not a number")
    return float(node)


def check_metric(
    cache: dict[str, Any], name: str, claimed: float, binding: dict[str, Any]
) -> None:
    if "path" in binding:
        pointer = str(binding["path"])
        actual = resolve_pointer(cache, pointer)
        rationale = str(binding.get("path_rationale", "")).strip()
        if not path_names_the_metric(name, pointer) and not rationale:
            raise BindingError(
                f"the path {pointer.split('#', 1)[-1]!r} shares no word with the "
                f"metric name. Point at the field that holds this quantity, or "
                f"state a path_rationale for the mismatch"
            )
        scale = float(binding.get("scale", 1))
        actual *= scale
        if "rounded_to" in binding:
            decimals = binding["rounded_to"]
            if not isinstance(decimals, int) or isinstance(decimals, bool) or decimals < 0:
                raise BindingError(
                    f"rounded_to must be a non-negative integer, not {decimals!r}"
                )
            rounded = round(actual, decimals)
            if abs(rounded - claimed) > 1e-9:
                raise BindingError(
                    f"claims {claimed}, artifact gives {actual:.6g}, which rounds to "
                    f"{rounded:.6g} at {decimals} decimal(s)"
                )
            return
    elif "derived" in binding:
        match = _DERIVED.match(str(binding["derived"]).strip())
        if not match:
            raise BindingError(
                f"derivation {binding['derived']!r} is not supported; "
                f"only wilson_upper(<k>, <n>) is"
            )
        k = resolve_pointer(cache, match.group(1))
        n = resolve_pointer(cache, match.group(2))
        actual = wilson_upper(k, n) * float(binding.get("scale", 1))
    else:
        raise BindingError("binding declares neither a path nor a derivation")

    if abs(actual - claimed) > TOLERANCE:
        raise BindingError(
            f"claims {claimed}, artifact gives {actual:.6g} "
            f"(tolerance {TOLERANCE})"
        )


def main() -> int:
    try:
        import yaml
    except ImportError:
        print("[SKIP] pyyaml is not installed; cannot read the claim register")
        return 0

    register = yaml.safe_load(REGISTER_PATH.read_text(encoding="utf-8"))
    baseline = (
        json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        if BASELINE_PATH.exists()
        else {"unbound_metrics": 0}
    )

    errors: list[str] = []
    unbound: list[str] = []
    bound = 0
    cache: dict[str, Any] = {}

    for claim in register.get("claims", []):
        if claim.get("status") != "active":
            continue
        metrics = claim.get("metrics") or {}
        numeric = {
            name: value
            for name, value in metrics.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if not numeric:
            continue

        bindings = claim.get("metric_bindings")
        if bindings is None:
            errors.append(
                f"{claim['id']}: publishes {len(numeric)} numeric metric(s) with no "
                f"metric_bindings block. Every number must point at its artifact or "
                f"say why it cannot"
            )
            continue

        by_path: dict[str, list[str]] = {}
        for name, binding in bindings.items():
            if isinstance(binding, dict) and "path" in binding:
                by_path.setdefault(str(binding["path"]).strip(), []).append(name)
        for pointer, names in sorted(by_path.items()):
            if len(names) > 1:
                errors.append(
                    f"{claim['id']}: {', '.join(sorted(names))} all bind {pointer}. "
                    f"One field cannot be the evidence for two different numbers"
                )

        for name, value in numeric.items():
            binding = bindings.get(name)
            if binding is None:
                errors.append(f"{claim['id']}.{name}: no binding declared")
                continue
            if "unbound" in binding:
                reason = str(binding["unbound"]).strip()
                if not reason:
                    errors.append(f"{claim['id']}.{name}: declared unbound with no reason")
                else:
                    unbound.append(f"{claim['id']}.{name}: {reason}")
                continue
            try:
                check_metric(cache, name, float(value), binding)
                bound += 1
            except BindingError as exc:
                errors.append(f"{claim['id']}.{name}: {exc}")

    for line in unbound:
        print(f"[WARN] (declared unbound) {line}")

    if errors:
        print("Claim metric binding gate FAILED:")
        for line in errors:
            print(f" - {line}")
        return 1

    allowed = int(baseline.get("unbound_metrics", 0))
    if len(unbound) > allowed:
        print(
            f"Claim metric binding gate FAILED: {len(unbound)} unbound metric(s), "
            f"baseline allows {allowed}. Bind the new number or lower nothing."
        )
        return 1

    print(
        f"[OK] Claim metric binding gate passed: {bound} metric(s) resolved to their "
        f"artifact, {len(unbound)} declared unbound (baseline {allowed})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
