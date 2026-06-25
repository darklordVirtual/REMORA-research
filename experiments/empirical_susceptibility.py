#!/usr/bin/env python3
"""Empirical susceptibility sweep — Sprint 5.

Measures empirical susceptibility χ_emp by computing the variance of the
order parameter η across a sliding temperature window, rather than using
the analytic synthetic χ in remora/thermodynamics.py.

Background
----------
In statistical physics, susceptibility χ = ∂⟨M⟩/∂h (derivative of
magnetisation with respect to external field) or equivalently:

    χ = (1/T) · Var(M)   (fluctuation-dissipation theorem)

Applied to oracle consensus, we approximate this as:

    χ_emp(T_c ± δ) = Var(η | T ∈ [T_c − δ, T_c + δ]) / T_c

This requires a committed artifact with per-item (T, η) values.
It does NOT require live oracle calls.

Relationship to thermodynamics.py
----------------------------------
thermodynamics.py computes χ_synthetic = chi_scale · ε(η, T_c).
This experiment measures χ_emp directly from the data distribution.
The two should agree qualitatively if the analogy is valid.

Usage
-----
    python experiments/empirical_susceptibility.py

or with a custom artifact:

    python experiments/empirical_susceptibility.py --artifact results/thermodynamic_eval_results.json

Output: results/empirical_susceptibility_results.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_artifact(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def extract_t_eta_pairs(data: dict) -> list[tuple[float, float]]:
    """Extract (temperature, eta) pairs from a thermodynamic eval artifact."""
    items = data.get("items", [])
    pairs = []
    for item in items:
        T = item.get("temperature")
        eta = item.get("order_parameter") or item.get("eta")
        if T is not None and eta is not None:
            try:
                pairs.append((float(T), float(eta)))
            except (TypeError, ValueError):
                continue
    return pairs


def window_statistics(
    pairs: list[tuple[float, float]],
    T_c: float,
    delta: float,
) -> dict:
    """Statistics of η within a temperature window [T_c − δ, T_c + δ].

    Returns
    -------
    dict with keys: n, mean_eta, var_eta, chi_emp, window
    """
    window_pairs = [(T, eta) for T, eta in pairs if abs(T - T_c) <= delta]
    n = len(window_pairs)
    if n < 2:
        return {
            "n": n,
            "mean_eta": None,
            "var_eta": None,
            "chi_emp": None,
            "window": [T_c - delta, T_c + delta],
            "note": "Too few items in window for variance estimate",
        }
    etas = [eta for _, eta in window_pairs]
    m = mean(etas)
    s = stdev(etas)  # sample std
    var_eta = s ** 2
    # χ_emp = Var(η) / T_c  (dimensionless; T_c used as normalising scale)
    chi_emp = var_eta / max(T_c, 1e-9)
    return {
        "n": n,
        "mean_eta": m,
        "var_eta": var_eta,
        "chi_emp": chi_emp,
        "window": [T_c - delta, T_c + delta],
    }


def phase_variance_summary(
    pairs: list[tuple[float, float]],
    T_c: float,
) -> dict:
    """Compare η variance across ordered / critical / disordered phases."""
    ordered = [eta for T, eta in pairs if T < 0.8 * T_c]
    critical_band = 0.15
    critical = [eta for T, eta in pairs if abs(T - T_c) / T_c <= critical_band]
    disordered = [eta for T, eta in pairs if T > T_c * (1 + critical_band)]

    def phase_stats(etas: list[float], name: str) -> dict:
        n = len(etas)
        if n < 2:
            return {"phase": name, "n": n, "mean_eta": None, "var_eta": None, "chi_emp": None}
        m = mean(etas)
        s = stdev(etas)
        var_eta = s ** 2
        return {
            "phase": name,
            "n": n,
            "mean_eta": round(m, 6),
            "var_eta": round(var_eta, 6),
            "chi_emp": round(var_eta / max(T_c, 1e-9), 6),
        }

    return {
        "ordered": phase_stats(ordered, "ordered"),
        "critical": phase_stats(critical, "critical"),
        "disordered": phase_stats(disordered, "disordered"),
    }


def spearman_rho(xs: list[float], ys: list[float]) -> float | None:
    """Compute Spearman rank correlation between two lists."""
    n = len(xs)
    if n < 3:
        return None

    def rank(vals: list[float]) -> list[float]:
        indexed = sorted(enumerate(vals), key=lambda x: x[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and indexed[j + 1][1] == indexed[j][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    rx = rank(xs)
    ry = rank(ys)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    denom = n * (n ** 2 - 1)
    if denom == 0:
        return None
    return 1.0 - 6.0 * d2 / denom


def correlation_chi_vs_temperature(
    pairs: list[tuple[float, float]],
    T_c: float,
    delta: float,
) -> dict:
    """Spearman ρ(T, χ_synthetic) as a function of window position.

    Sweeps δ_windows centered at T_c and computes the Spearman
    correlation between temperature and η within each window.
    """
    results = []
    for window_frac in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]:
        d = T_c * window_frac
        window_pairs = [(T, eta) for T, eta in pairs if abs(T - T_c) <= d]
        if len(window_pairs) < 5:
            continue
        Ts = [p[0] for p in window_pairs]
        etas = [p[1] for p in window_pairs]
        rho = spearman_rho(Ts, etas)
        results.append({
            "window_frac": window_frac,
            "delta": round(d, 4),
            "n": len(window_pairs),
            "spearman_rho_T_eta": round(rho, 4) if rho is not None else None,
        })
    return {"T_c": T_c, "delta_base": delta, "windows": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Empirical susceptibility sweep")
    parser.add_argument(
        "--artifact",
        default="results/thermodynamic_eval_results.json",
        help="Thermodynamic eval artifact with per-item T and eta values",
    )
    parser.add_argument(
        "--T-c",
        type=float,
        default=None,
        help="Critical temperature (default: read from artifact summary or 1.0)",
    )
    parser.add_argument(
        "--delta",
        type=float,
        default=None,
        help="Window half-width for χ_emp (default: 15%% of T_c)",
    )
    args = parser.parse_args()

    artifact_path = ROOT / args.artifact
    print(f"Loading artifact: {artifact_path}")
    data = load_artifact(artifact_path)

    pairs = extract_t_eta_pairs(data)
    print(f"Extracted {len(pairs)} (T, η) pairs")
    if len(pairs) < 10:
        print("ERROR: Too few items to compute meaningful susceptibility.", file=sys.stderr)
        return 1

    # Determine T_c
    T_c = args.T_c
    if T_c is None:
        T_c = data.get("summary", {}).get("T_c") or 1.0
    print(f"Using T_c = {T_c:.4f}")

    delta = args.delta if args.delta is not None else 0.15 * T_c

    # Core susceptibility window
    window_stats = window_statistics(pairs, T_c, delta)

    # Phase-level variance summary
    phase_summary = phase_variance_summary(pairs, T_c)

    # Correlation sweep
    corr_sweep = correlation_chi_vs_temperature(pairs, T_c, delta)

    # Global distribution summary
    all_etas = [eta for _, eta in pairs]
    all_Ts = [T for T, _ in pairs]
    global_summary = {
        "n_total": len(pairs),
        "T_mean": round(mean(all_Ts), 4),
        "T_std": round(stdev(all_Ts) if len(all_Ts) > 1 else 0.0, 4),
        "eta_mean": round(mean(all_etas), 4),
        "eta_std": round(stdev(all_etas) if len(all_etas) > 1 else 0.0, 4),
        "spearman_rho_T_eta_global": round(
            spearman_rho(all_Ts, all_etas) or 0.0, 4
        ),
    }

    # Scientific note
    synthetic_note = (
        "chi_emp is computed from Var(eta) / T_c within the critical window. "
        "This differs from thermodynamics.py's chi_synthetic which uses a local "
        "delta around eta and T_c analytically. Agreement between these two is "
        "a validation target for the thermodynamic analogy."
    )

    result = {
        "artifact": str(artifact_path.relative_to(ROOT)),
        "T_c": T_c,
        "delta": round(delta, 4),
        "global_summary": global_summary,
        "critical_window_susceptibility": window_stats,
        "phase_variance_summary": phase_summary,
        "correlation_sweep": corr_sweep,
        "methodology_note": synthetic_note,
    }

    out_path = ROOT / "results" / "empirical_susceptibility_results.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nResults written to: {out_path}")

    # Summary
    if window_stats.get("chi_emp") is not None:
        print(f"\nχ_emp (critical window): {window_stats['chi_emp']:.6f}")
        print(f"  n_critical_window: {window_stats['n']}")
        print(f"  mean_eta: {window_stats['mean_eta']:.4f}")
        print(f"  var_eta: {window_stats['var_eta']:.6f}")
    else:
        print(f"\nχ_emp: not computable ({window_stats.get('note')})")

    crit_phase = phase_summary.get("critical", {})
    if crit_phase.get("chi_emp") is not None:
        print(f"\nPhase-level χ_emp (critical): {crit_phase['chi_emp']:.6f}  (n={crit_phase['n']})")
    else:
        print("\nPhase-level χ_emp (critical): not computable")

    print(f"\nGlobal Spearman ρ(T, η): {global_summary['spearman_rho_T_eta_global']:+.4f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
