# Author: Stian Skogbrott
# License: Apache-2.0
#!/usr/bin/env python3
"""
Three-condition ablation study for REMORA.

Conditions:
  A) Single oracle    — Llama 3.3 70b alone (strongest single baseline)
  B) Unweighted majority — 3 oracles, plain majority vote
  C) REMORA (full)   — 3 oracles + diversity weighting + Lyapunov abort gate

Dataset: 75 manually curated polarity items (25 DCE + 25 SCI + 25 FACT)

Outputs:
  ablation_results.json   (machine-readable)
  ablation_report.txt     (human-readable, suitable for paper appendix)
"""
from __future__ import annotations
import json
import math
import time
from collections import defaultdict
from pathlib import Path

from remora.benchmarks.loaders import BenchmarkItem
from remora.benchmarks.extended import load_all_extended
from remora.canonical import phi
from remora.correlation import CorrelationMatrix
from remora.oracles.groq import GroqOracle
from remora.genome import Genome, RouterMode
from remora.engine import Remora
from remora.persistence import CachedOracle, Store
from remora.scoring import score_one, _polarity_match

ORACLE_MODELS = [
    "llama-3.3-70b-versatile",
    "anthropic/claude-3.5-sonnet",
    "openai/gpt-4o",
]
STRONG_SINGLE = "llama-3.3-70b-versatile"


def build_eval_prompt(item: BenchmarkItem) -> str:
    ctx = f"\nContext:\n{item.context}\n" if item.context else ""
    return (f"{ctx}Answer the question below. Return ONLY valid JSON.\n"
        'Format: {"claim": "<specific statement>", "answer": true|false|null, "confidence": 0.0-1.0}\n\n'
        f"Question: {item.question}\n\nJSON:")


def load_dataset() -> list[BenchmarkItem]:
    return load_all_extended()


def run_single_oracle(items: list[BenchmarkItem], oracle) -> list[dict]:
    results = []
    for item in items:
        resp = oracle.ask(build_eval_prompt(item))
        verdict = phi(resp.extracted)
        results.append({"item_id": item.item_id, "benchmark": item.benchmark,
            "correct": _polarity_match(verdict.polarity, item.ground_truth),
            "predicted": verdict.polarity, "expected": item.ground_truth, "oracle_calls": 1})
    return results


def run_unweighted_majority(items: list[BenchmarkItem], oracles: list) -> list[dict]:
    results = []
    correlation = CorrelationMatrix(window_size=500)
    for item in items:
        prompt = build_eval_prompt(item)
        verdicts = [(oracle.name, phi(oracle.ask(prompt).extracted)) for oracle in oracles]
        correlation.observe(verdicts)
        votes: dict = defaultdict(float)
        for _, v in verdicts: votes[v.polarity] += 1
        winner = max(votes, key=votes.__getitem__)
        results.append({"item_id": item.item_id, "benchmark": item.benchmark,
            "correct": _polarity_match(winner, item.ground_truth),
            "predicted": winner, "expected": item.ground_truth, "oracle_calls": len(oracles),
            "vote_distribution": {str(k): v for k, v in votes.items()}})
    return results


def run_remora(items: list[BenchmarkItem], oracles: list, genome: Genome) -> tuple:
    correlation = CorrelationMatrix(window_size=500)
    remora = Remora(oracles=oracles, genome=genome, correlation=correlation)
    results = []
    for item in items:
        state = remora.run(item.question, context=item.context)
        report = remora.report(state)
        score = score_one(item, report)
        traj = report.get("trajectory", [])
        results.append({"item_id": item.item_id, "benchmark": item.benchmark,
            "correct": score.correct, "predicted": score.predicted, "expected": score.expected,
            "oracle_calls": report["oracle_calls"], "iterations": report["iterations"],
            "converged": report["is_converging"],
            "aborted": any("abort" in d for d in report.get("decisions", [])),
            "routed": any("router_gate" in d for d in report.get("decisions", [])),
            "v_trajectory": [s["V"] for s in traj], "final_V": report.get("final_V") or 0.0})
    oracle_names = [o.name for o in oracles]
    rho_matrix = correlation.rho_matrix(oracle_names)
    off_diag = [rho_matrix[a][b] for a in oracle_names for b in oracle_names if a != b]
    mean_rho = sum(off_diag) / len(off_diag) if off_diag else 0.0
    return results, mean_rho, correlation.diversity_weights(oracle_names), rho_matrix


def accuracy(results: list[dict]) -> float:
    return sum(1 for r in results if r["correct"]) / len(results) if results else 0.0


def wilson_ci(n_correct: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0: return 0.0, 0.0
    p = n_correct / n; denom = 1 + z**2/n
    center = (p + z**2/(2*n)) / denom
    spread = z * math.sqrt(p*(1-p)/n + z**2/(4*n**2)) / denom
    return max(0.0, center-spread), min(1.0, center+spread)


def per_bm(results: list[dict]) -> dict:
    by: dict = defaultdict(list)
    for r in results: by[r["benchmark"]].append(r)
    out = {}
    for bm, rs in by.items():
        n = len(rs); n_c = sum(1 for r in rs if r["correct"])
        lo, hi = wilson_ci(n_c, n)
        out[bm] = {"n": n, "correct": n_c, "accuracy": round(n_c/n, 4),
            "ci_95_lo": round(lo,4), "ci_95_hi": round(hi,4)}
    return out


def mono_rate(results: list[dict]) -> float:
    has = [r for r in results if r.get("v_trajectory")]
    return sum(1 for r in has if all(r["v_trajectory"][i] <= r["v_trajectory"][i-1]+0.01
        for i in range(1, len(r["v_trajectory"])))) / len(has) if has else 0.0


def router_analysis(results: list[dict]) -> dict:
    routed = [r for r in results if r.get("routed")]
    full = [r for r in results if not r.get("routed")]
    def acc(rs): return sum(1 for r in rs if r["correct"]) / len(rs) if rs else None
    return {"n_routed": len(routed), "n_full_remora": len(full),
        "route_rate": round(len(routed) / len(results), 4) if results else 0.0,
        "routed_accuracy": round(acc(routed), 4) if acc(routed) is not None else None,
        "full_remora_accuracy": round(acc(full), 4) if acc(full) is not None else None}


def false_conv_rescued(results_B: list[dict], results_C: list[dict]) -> float:
    wrong_B = sum(1 for r in results_B if not r["correct"])
    rescued = sum(1 for b,c in zip(results_B,results_C) if not b["correct"] and c["correct"])
    return rescued/wrong_B if wrong_B else 0.0


def format_report(exp: dict) -> str:
    A = exp["condition_A"]; B = exp["condition_B"]; C = exp["condition_C"]
    D1 = exp.get("condition_D1"); D2 = exp.get("condition_D2"); D3 = exp.get("condition_D3")
    meta = exp["meta"]; stats = exp["aggregate_stats"]; oc = exp["oracle_correlation"]
    w = 72
    bm_summary = ", ".join(f"{k}={v}" for k,v in meta["n_per_benchmark"].items())
    lines = ["="*w, "REMORA — SIX-CONDITION ABLATION STUDY",
        f"Timestamp:  {meta['timestamp']}",
        f"N =         {meta['n_items']} items ({bm_summary})",
        f"Oracles:    {', '.join(meta['oracles'])}", "="*w, "",
        "── CONDITIONS ──────────────────────────────────────────────────────",
        f"  A) Single oracle ({STRONG_SINGLE})",
        "  B) Unweighted majority: 3 oracles, plain majority vote",
        "  C) REMORA full: diversity weighting + Lyapunov abort gate",
        "  D1) REMORA + Router gate STRICT  (all 3 must agree → skip REMORA)",
        "  D2) REMORA + Router gate BALANCED (majority → skip REMORA)  [recommended]",
        "  D3) REMORA + Router gate HYBRID   (majority + conf≥0.80 → skip REMORA)",
        "      (identical prompt format across all conditions)", "",
        "── 1. EXTERNAL VALIDITY (accuracy) ─────────────────────────────────",
        f"  {'Benchmark':12s} {'A':>9s} {'B':>9s} {'C':>9s} {'D1':>9s} {'D2':>9s} {'D3':>9s}",
        "  " + "-"*60]
    all_bms = sorted(set(list(A["per_benchmark"]) + list(C["per_benchmark"])))
    for bm in all_bms:
        def f(cond, bm=bm):
            s = (cond or {}).get("per_benchmark", {}).get(bm, {})
            return f"{s['accuracy']:4.0%}({s['correct']}/{s['n']})" if s else "    —"
        lines.append(f"  {bm:12s} {f(A):>9s} {f(B):>9s} {f(C):>9s} {f(D1):>9s} {f(D2):>9s} {f(D3):>9s}")
    a_t=A["overall"]; b_t=B["overall"]; c_t=C["overall"]
    d1_t=(D1 or {}).get("overall",{}); d2_t=(D2 or {}).get("overall",{}); d3_t=(D3 or {}).get("overall",{})
    def ot(s): return f"{s['accuracy']:4.0%}({s['correct']}/{s['n']})" if s else "    —"
    lines += ["  "+"-"*60,
        f"  {'TOTAL':12s} {ot(a_t):>9s} {ot(b_t):>9s} {ot(c_t):>9s} {ot(d1_t):>9s} {ot(d2_t):>9s} {ot(d3_t):>9s}", "",
        "  95% Wilson confidence intervals:",
        f"    A  (single):    [{a_t['ci_lo']:.1%}, {a_t['ci_hi']:.1%}]",
        f"    B  (majority):  [{b_t['ci_lo']:.1%}, {b_t['ci_hi']:.1%}]",
        f"    C  (REMORA):    [{c_t['ci_lo']:.1%}, {c_t['ci_hi']:.1%}]"]
    if d1_t: lines.append(f"    D1 (strict):    [{d1_t['ci_lo']:.1%}, {d1_t['ci_hi']:.1%}]")
    if d2_t: lines.append(f"    D2 (balanced):  [{d2_t['ci_lo']:.1%}, {d2_t['ci_hi']:.1%}]")
    if d3_t: lines.append(f"    D3 (hybrid):    [{d3_t['ci_lo']:.1%}, {d3_t['ci_hi']:.1%}]")
    lines += ["── 2. ORACLE CORRELATION ────────────────────────────────────",
        f"  ρ̄ = {oc['mean_rho']:.4f}  (0=independent, 1=identical)",
        "  Correlation matrix:"]
    names = list(oc["rho_matrix"])
    for a in names:
        row = "  ".join(f"{oc['rho_matrix'][a][b]:.3f}" for b in names)
        lines.append(f"    {a.split('/')[-1][:18]:18s}: {row}")
    lines += ["  Diversity weights wₖ (normalised):"]
    for name, wk in oc["weights"].items():
        lines.append(f"    {name.split('/')[-1][:18]:18s}: {wk:.4f}")
    ls=stats["lyapunov"]; ce=stats["compute"]; sg=stats["swarm_gain"]
    lines += ["", "── 3. LYAPUNOV STABILITY (Condition C) ──────────────────────",
        f"  Monotonically decreasing V: {ls['monotone_V_rate']:.1%} of runs",
        f"  Abort gate triggered:       {ls['abort_rate']:.1%}",
        f"  Early convergence:          {ls['convergence_rate']:.1%}",
        f"  Mean iterations:            {ls['mean_iterations']:.2f} of max {ls['max_iterations']}",
        "", "── 4. COMPUTE EFFICIENCY (Condition C) ──────────────────────",
        f"  Actual oracle calls:   {ce['actual_calls']}",
        f"  Naive maximum:         {ce['max_calls']}",
        f"  Reduction via V-gate:  {ce['reduction']:.1%}",
        "", "── 5. SWARM GAIN ──────────────────────────────────────────────",
        f"  A → C (single → REMORA):     {sg['single_to_remora']:+.1%}",
        f"  B → C (majority → REMORA):   {sg['unweighted_to_remora']:+.1%}",
        f"  B errors rescued by C:       {sg['false_conv_rescued']:.1%}"]
    if d2_t and d2_t.get("accuracy") is not None:
        lines += [f"  B → D2 (majority → routed):  {d2_t['accuracy']-b_t['accuracy']:+.1%}",
                  f"  C → D2 (REMORA → routed):    {d2_t['accuracy']-c_t['accuracy']:+.1%}"]
    lines += ["", "── 6. PER-ITEM DETAILS ──────────────────────────────────────",
        f"  {'ID':10s} {'Benchmark':8s} {'A':5s} {'B':5s} {'C':5s} {'D2':5s} {'GT':8s}",
        "  "+"-"*52]
    raw_d2 = exp["raw"].get("D2", [{}]*len(exp["raw"]["A"]))
    for ar,br,cr,d2r in zip(exp["raw"]["A"],exp["raw"]["B"],exp["raw"]["C"],raw_d2):
        a_ok="✓" if ar["correct"] else "✗"
        b_ok="✓" if br["correct"] else "✗"
        c_ok="✓" if cr["correct"] else "✗"
        d2_ok="✓" if d2r.get("correct") else ("✗" if d2r else " ")
        route_flag = "⚡" if d2r.get("routed") else " "
        note = (" ← D2 wins" if not cr["correct"] and d2r.get("correct") else
                " ← D2 loses" if cr["correct"] and not d2r.get("correct") else "")
        lines.append(
            f"  {ar['item_id']:10s} {ar['benchmark']:8s} {a_ok:5s} {b_ok:5s} {c_ok:5s} "
            f"{d2_ok}{route_flag:4s} {str(ar['expected']):8s}{note}")
    lines += ["  (⚡ = router gate fired, skipped full REMORA)", ""]
    # Section 7 — Router gate analysis
    lines += ["── 7. ROUTER GATE ANALYSIS (D1/D2/D3) ──────────────────────"]
    for label, cond, raw_key in [("D1 STRICT  ", D1, "D1"), ("D2 BALANCED", D2, "D2"), ("D3 HYBRID  ", D3, "D3")]:
        if not cond:
            lines.append(f"  {label}: not run")
            continue
        ra = exp.get("router_stats", {}).get(raw_key, {})
        n_r = ra.get("n_routed", 0); n_f = ra.get("n_full_remora", 0)
        rate = ra.get("route_rate", 0); r_acc = ra.get("routed_accuracy"); f_acc = ra.get("full_remora_accuracy")
        r_acc_s = f"{r_acc:.1%}" if r_acc is not None else "—"
        f_acc_s = f"{f_acc:.1%}" if f_acc is not None else "—"
        lines.append(f"  {label}: route_rate={rate:.0%}  routed={n_r}({r_acc_s})  full_REMORA={n_f}({f_acc_s})")
    lines += ["", "="*w, "Saved: results/ablation_results.json  +  results/ablation_report.txt", "="*w]
    return "\n".join(lines)


def main() -> None:
    print("\nLoading dataset...")
    items = load_dataset()
    print(f"Total: {len(items)} items")
    for bm in sorted(set(i.benchmark for i in items)):
        print(f"  {bm:12s}: {sum(1 for i in items if i.benchmark==bm)}")
    store = Store(".remora_cache_mixed.json")
    from remora.oracles.factory import build_mixed_swarm
    raw_oracles = build_mixed_swarm()
    cached_oracles = [CachedOracle(o, store) for o in raw_oracles]
    single_oracle = CachedOracle(GroqOracle(STRONG_SINGLE), store)
    genome = Genome(max_iterations=4, max_subquestions=1, converged_threshold=0.72,
        entropy_abort_ratio=1.3, negation_ratio=0.25)
    print(f"\n[A] Single oracle: {STRONG_SINGLE}")
    t0=time.perf_counter(); res_A=run_single_oracle(items, single_oracle); tA=time.perf_counter()-t0
    n_A=len(res_A); n_c_A=sum(1 for r in res_A if r["correct"]); lo_A,hi_A=wilson_ci(n_c_A,n_A)
    print(f"    {n_c_A}/{n_A} = {n_c_A/n_A:.1%}  CI [{lo_A:.1%}, {hi_A:.1%}]  ({tA:.0f}s)")
    print("\n[B] Unweighted majority (3 oracles)")
    t0=time.perf_counter(); res_B=run_unweighted_majority(items, cached_oracles); tB=time.perf_counter()-t0
    n_B=len(res_B); n_c_B=sum(1 for r in res_B if r["correct"]); lo_B,hi_B=wilson_ci(n_c_B,n_B)
    print(f"    {n_c_B}/{n_B} = {n_c_B/n_B:.1%}  CI [{lo_B:.1%}, {hi_B:.1%}]  ({tB:.0f}s)")
    print("\n[C] REMORA (full system)")
    t0=time.perf_counter(); res_C,mean_rho,weights,rho_matrix=run_remora(items,cached_oracles,genome); tC=time.perf_counter()-t0
    n_C=len(res_C); n_c_C=sum(1 for r in res_C if r["correct"]); lo_C,hi_C=wilson_ci(n_c_C,n_C)
    print(f"    {n_c_C}/{n_C} = {n_c_C/n_C:.1%}  CI [{lo_C:.1%}, {hi_C:.1%}]  ({tC:.0f}s)")

    base_genome = dict(max_iterations=4, max_subquestions=1, converged_threshold=0.72,
        entropy_abort_ratio=1.3, negation_ratio=0.25, enable_routing=True)
    genome_D1 = Genome(**base_genome, router_mode=RouterMode.STRICT)
    genome_D2 = Genome(**base_genome, router_mode=RouterMode.BALANCED)
    genome_D3 = Genome(**base_genome, router_mode=RouterMode.HYBRID, router_confidence_min=0.80)

    print("\n[D1] REMORA + Router gate STRICT  (all 3 must agree)")
    t0=time.perf_counter(); res_D1,_,_,_=run_remora(items,cached_oracles,genome_D1); tD1=time.perf_counter()-t0
    n_D1=len(res_D1); n_c_D1=sum(1 for r in res_D1 if r["correct"]); lo_D1,hi_D1=wilson_ci(n_c_D1,n_D1)
    print(f"    {n_c_D1}/{n_D1} = {n_c_D1/n_D1:.1%}  CI [{lo_D1:.1%}, {hi_D1:.1%}]  ({tD1:.0f}s)  "
          f"routed={sum(1 for r in res_D1 if r.get('routed'))}/{n_D1}")

    print("\n[D2] REMORA + Router gate BALANCED (majority)")
    t0=time.perf_counter(); res_D2,_,_,_=run_remora(items,cached_oracles,genome_D2); tD2=time.perf_counter()-t0
    n_D2=len(res_D2); n_c_D2=sum(1 for r in res_D2 if r["correct"]); lo_D2,hi_D2=wilson_ci(n_c_D2,n_D2)
    print(f"    {n_c_D2}/{n_D2} = {n_c_D2/n_D2:.1%}  CI [{lo_D2:.1%}, {hi_D2:.1%}]  ({tD2:.0f}s)  "
          f"routed={sum(1 for r in res_D2 if r.get('routed'))}/{n_D2}")

    print("\n[D3] REMORA + Router gate HYBRID   (majority + conf>=0.80)")
    t0=time.perf_counter(); res_D3,_,_,_=run_remora(items,cached_oracles,genome_D3); tD3=time.perf_counter()-t0
    n_D3=len(res_D3); n_c_D3=sum(1 for r in res_D3 if r["correct"]); lo_D3,hi_D3=wilson_ci(n_c_D3,n_D3)
    print(f"    {n_c_D3}/{n_D3} = {n_c_D3/n_D3:.1%}  CI [{lo_D3:.1%}, {hi_D3:.1%}]  ({tD3:.0f}s)  "
          f"routed={sum(1 for r in res_D3 if r.get('routed'))}/{n_D3}")

    oracle_names=[o.name for o in raw_oracles]
    n_aborted=sum(1 for r in res_C if r.get("aborted")); n_converged=sum(1 for r in res_C if r.get("converged"))
    actual_calls=sum(r.get("oracle_calls",0) for r in res_C); max_calls=len(items)*genome.max_iterations*len(raw_oracles)
    def cond_block(results, n_c, n, lo, hi):
        return {"overall": {"accuracy":round(n_c/n,4),"correct":n_c,"n":n,
            "ci_lo":round(lo,4),"ci_hi":round(hi,4)}, "per_benchmark": per_bm(results)}
    def strip_traj(results):
        return [{k:v for k,v in r.items() if k!="v_trajectory"} for r in results]
    experiment = {
        "meta": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_items": len(items),
            "n_per_benchmark": {bm: sum(1 for i in items if i.benchmark==bm)
                for bm in sorted(set(i.benchmark for i in items))},
            "oracles": oracle_names, "single_oracle": STRONG_SINGLE,
            "genome": {"max_iterations": genome.max_iterations,
                "converged_threshold": genome.converged_threshold}},
        "oracle_correlation": {"mean_rho": round(mean_rho,4),
            "rho_matrix": {a:{b:round(v,4) for b,v in row.items()} for a,row in rho_matrix.items()},
            "weights": {k:round(v,4) for k,v in weights.items()}},
        "condition_A": cond_block(res_A, n_c_A, n_A, lo_A, hi_A),
        "condition_B": cond_block(res_B, n_c_B, n_B, lo_B, hi_B),
        "condition_C": cond_block(res_C, n_c_C, n_C, lo_C, hi_C),
        "condition_D1": cond_block(res_D1, n_c_D1, n_D1, lo_D1, hi_D1),
        "condition_D2": cond_block(res_D2, n_c_D2, n_D2, lo_D2, hi_D2),
        "condition_D3": cond_block(res_D3, n_c_D3, n_D3, lo_D3, hi_D3),
        "router_stats": {
            "D1": router_analysis(res_D1),
            "D2": router_analysis(res_D2),
            "D3": router_analysis(res_D3),
        },
        "aggregate_stats": {
            "lyapunov": {"monotone_V_rate":round(mono_rate(res_C),4),"abort_rate":round(n_aborted/len(items),4),
                "convergence_rate":round(n_converged/len(items),4),
                "mean_iterations":round(sum(r.get("iterations",4) for r in res_C)/len(items),2),
                "max_iterations":genome.max_iterations},
            "compute": {"actual_calls":actual_calls,"max_calls":max_calls,
                "reduction":round(1-actual_calls/max_calls,4),
                "mean_calls_per_item":round(actual_calls/len(items),2)},
            "swarm_gain": {"single_to_remora":round(n_c_C/n_C-n_c_A/n_A,4),
                "unweighted_to_remora":round(n_c_C/n_C-n_c_B/n_B,4),
                "false_conv_rescued":round(false_conv_rescued(res_B,res_C),4)}},
        "raw": {"A":res_A,"B":res_B,
            "C":strip_traj(res_C),"D1":strip_traj(res_D1),
            "D2":strip_traj(res_D2),"D3":strip_traj(res_D3)}}
    report_text = format_report(experiment)
    safe_report = report_text.encode("ascii", errors="replace").decode("ascii")
    print("\n" + safe_report)
    results_dir = Path(__file__).resolve().parents[1] / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / "ablation_results.json").write_text(json.dumps(experiment, ensure_ascii=False, indent=2), encoding="utf-8")
    (results_dir / "ablation_report.txt").write_text(report_text, encoding="utf-8")


if __name__ == "__main__":
    main()
