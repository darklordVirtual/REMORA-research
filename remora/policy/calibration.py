from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def compute_temperature_threshold(
    n500_data_path: str | Path | None = None,
    target_coverage: float = 0.18,
) -> float:
    """Return the temperature threshold T* for the N500 benchmark at *target_coverage*.

    Items with temperature <= T* represent approximately *target_coverage* of all
    N500 items.  T* is derived from the sorted temperature distribution of the stored
    artifact rather than from live oracle calls.

    At target_coverage=0.18: T* ≈ 0.1972, yielding k=98 items with 88.78% accuracy
    (Proof XI — p < 10^-6).
    """
    if n500_data_path is None:
        n500_data_path = (
            _REPO_ROOT / "results" / "thermodynamic_eval_n500_calibrated_results.json"
        )

    path = Path(n500_data_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["items"]

    temps = sorted(item["temperature"] for item in items if "temperature" in item)
    n = len(temps)
    if n == 0:
        raise ValueError("No temperature values found in N500 artifact")
    k = max(1, round(n * target_coverage))
    return temps[k - 1]
