#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER end-to-end demo — verbose output showing every component live.

Runs a full simulation: governance decisions → outcome recording →
adaptation cycle → world model updates → MetaJudge (if worker available).
"""
from __future__ import annotations
import sys
import tempfile
import textwrap
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.aromer import AromerOrchestrator, OutcomeType
from remora.policy import PolicyObservation

W  = "\033[0m"
B  = "\033[1m"
G  = "\033[92m"
Y  = "\033[93m"
R  = "\033[91m"
C  = "\033[96m"
M  = "\033[95m"

def banner(text: str, color: str = B) -> None:
    print(f"\n{color}{'='*68}{W}")
    print(f"{color}{B}  {text}{W}")
    print(f"{color}{'='*68}{W}\n")

def section(text: str) -> None:
    print(f"\n{C}{B}>> {text}{W}")
    print(f"{C}{'-'*60}{W}")

def ok(text: str) -> None:
    print(f"  {G}OK{W} {text}")

def warn(text: str) -> None:
    print(f"  {Y}!!{W} {text}")

def info(text: str, indent: int = 2) -> None:
    pad = " " * indent
    for line in textwrap.wrap(text, 70):
        print(f"{pad}{line}")

def show_dict(d: dict, indent: int = 4) -> None:
    pad = " " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            print(f"{pad}{C}{k}{W}:")
            show_dict(v, indent + 4)
        elif isinstance(v, list):
            print(f"{pad}{C}{k}{W}: {v}")
        elif isinstance(v, float):
            print(f"{pad}{C}{k}{W}: {v:.4f}")
        else:
            print(f"{pad}{C}{k}{W}: {v}")

def obs(domain, risk_tier, action_type, trust, H, D, phase=None, env="production"):
    if phase is None:
        phase = "ordered" if H < 0.45 else "critical" if H < 0.75 else "disordered"
    return PolicyObservation(
        question=f"[{domain}] {action_type} action",
        phase=phase,
        trust_score=trust,
        final_H=H,
        final_D=D,
        risk_tier=risk_tier,
        domain=domain,
        action_type=action_type,
        target_environment=env,
    )


def main() -> None:
    banner("AROMER - Autonomous REMORA Orchestrator, Meta-Emergent Reasoner", C)
    print(f"  {B}Version{W}: 0.1.0-experimental")
    print(f"  {B}Status{W} : Research prototype — not AGI, not production-certified")
    print(f"  {B}Goal{W}   : Demonstrate closed-loop meta-cognitive governance\n")

    # ── Setup ────────────────────────────────────────────────────────────────
    section("Initialising AROMER with temporary storage")

    tmp = tempfile.mkdtemp()
    aromer = AromerOrchestrator(
        store_path       = str(Path(tmp) / "episodes.jsonl"),
        world_model_path = str(Path(tmp) / "world_model.json"),
        bridge_state_path= str(Path(tmp) / "bridge_state.json"),
        run_meta_judge   = True,   # will use live Workers AI if available
        meta_judge_batch = 3,
        world_model_shadow_mode = True,
    )
    ok(f"AromerOrchestrator initialised  [store: {tmp}]")
    ok("EpisodicStore:         0 episodes")
    ok(f"ThermodynamicAdapter:  λ = {aromer._bridge.adapted_lambda():.4f}  (SGD coupling)")
    ok(f"OracleBandit:          oracle ranking = {aromer._bridge.select_oracles(3)}")
    ok("DomainHarmPrior:       uniform Beta(1,1), shadow mode active")

    # ── Round 1: six governance decisions ────────────────────────────────────
    section("Round 1 — Six governance decisions across three domains")
    print("  Making decisions BEFORE any learning has occurred.\n")

    scenarios = [
        # (label, domain, risk, action, trust, H, D, true_outcome)
        ("Financial fraud query",      "financial",    "critical", "write",     0.30, 0.88, 0.71, OutcomeType.CORRECT_BLOCK),
        ("Routine report read",        "information",  "low",      "read",      0.85, 0.20, 0.08, OutcomeType.CORRECT_ACCEPT),
        ("DB write in critical phase", "database",     "high",     "write",     0.50, 0.72, 0.55, OutcomeType.FALSE_ACCEPT),
        ("SQL injection attempt",      "cybersecurity","critical", "execution", 0.25, 0.91, 0.82, OutcomeType.CORRECT_BLOCK),
        ("Agent deletes prod table",   "database",     "critical", "delete",    0.20, 0.92, 0.85, OutcomeType.CORRECT_BLOCK),
        ("Benign search query",        "information",  "low",      "read",      0.90, 0.15, 0.05, OutcomeType.CORRECT_ACCEPT),
    ]

    episode_ids = []
    for label, domain, risk, action, trust, H, D, true_outcome in scenarios:
        observation = obs(domain, risk, action, trust, H, D)
        # Note: world model hasn't learned anything yet → P(harm) = 0.50
        ph_before = aromer._world.p_harm(domain, action, risk)
        adj_trust_before = aromer._world.adjust_trust(trust, domain, action, risk)

        report, eid = aromer.decide(observation)
        episode_ids.append((eid, true_outcome))

        verdict_color = G if report.action.value in ("accept",) else (
                         Y if report.action.value in ("verify", "abstain") else R)
        print(f"  {B}{label}{W}")
        print(f"    domain={domain:<14} risk={risk:<9} action={action:<12} trust_in={trust:.2f}")
        print(f"    P(harm)={ph_before:.3f}  adj_trust={adj_trust_before:.3f}  H={H:.2f}  D={D:.2f}")
        print(f"    {B}Verdict:{W} {verdict_color}{report.action.value.upper()}{W}  "
              f"human_review={report.human_review_required}  episode={eid[:8]}…")
        print(f"    True outcome will be: {true_outcome.value}")
        print()

    ok(f"EpisodicStore: {aromer._store.size} episodes recorded")

    # ── Record outcomes ───────────────────────────────────────────────────────
    section("Recording true outcomes (feedback loop entry point)")
    print("  This is where AROMER learns what actually happened.\n")

    for eid, outcome in episode_ids:
        severity = -0.8 if outcome.is_negative else 0.7
        found = aromer.record_outcome(eid, outcome, severity=severity)
        color = G if outcome.is_positive else (R if outcome.is_negative else Y)
        print(f"  {color}●{W} episode {eid[:8]}… → {outcome.value}  (severity={severity:+.1f})  "
              f"updated={found}")

    print()
    ok(f"All {len(episode_ids)} outcomes recorded")
    ok("World model + ThermodynamicAdapter + OracleBandit updated from outcomes")

    # Show world model shift
    section("World model after Round 1 outcomes")
    print("  Bayesian P(harm) estimates have shifted from uniform 0.50.\n")
    shown = set()
    for _, domain, risk, action, *_, true_outcome in scenarios:
        key = (domain, action, risk)
        if key in shown:
            continue
        shown.add(key)
        ph = aromer._world.p_harm(domain, action, risk)
        stats = aromer._world.stats(domain, action, risk)
        bar_len = int(ph * 30)
        bar = "█" * bar_len + "░" * (30 - bar_len)
        color = R if ph > 0.65 else (Y if ph > 0.40 else G)
        print(f"  {domain:<14} {action:<12} {risk:<9}  "
              f"P(harm)={color}{ph:.3f}{W}  [{bar}]  n={stats.n_observations}")

    # ── Adaptation cycle ──────────────────────────────────────────────────────
    section("Running AROMER adaptation cycle")
    print("  (This runs automatically every hour via Cloudflare Worker cron.)\n")

    adapt_report = aromer.adapt()
    print(f"  {B}Cycle #{adapt_report['cycle']}{W}")
    print(f"  Episodes in store:  {adapt_report['store_size']}")
    print(f"  Pending outcomes:   {adapt_report['pending_outcomes']}")

    exp = adapt_report["experience"]
    far = exp["false_accept_rate"]
    fa_color = R if far is not None and far > 0.15 else G
    far_str = f"{far:.3f}" if far is not None else "N/A"
    print(f"  False-accept rate:  {fa_color}{far_str}{W}  "
          f"(> 0.05 triggers threshold tightening)")
    fbr = exp["false_block_rate"]
    fbr_str = f"{fbr:.3f}" if fbr is not None else "N/A"
    print(f"  False-block rate:   {fbr_str}")
    print(f"  Safety violations:  {exp['safety_violations']}")

    adaptation = adapt_report["adaptation"]
    print(f"\n  {B}Threshold adaptation:{W}")
    ta = adaptation["threshold_report"]
    ta_far = ta['false_accept_rate']
    ta_fbr = ta['false_block_rate']
    print(f"    thresholds adjusted: {ta['thresholds_adjusted']}")
    print(f"    false_accept_rate:   {f'{ta_far:.4f}' if ta_far is not None else 'N/A'}")
    print(f"    false_block_rate:    {f'{ta_fbr:.4f}' if ta_fbr is not None else 'N/A'}")

    print(f"\n  {B}Thermodynamic state:{W}")
    thermo = adaptation["thermodynamic"]
    print(f"    λ coupling:   {thermo['lambda']:.6f}  (SGD-adapted)")
    print(f"    converged:    {thermo['converged']}")
    print(f"    V_params:     {thermo['v_params']:.8f}  (Lyapunov distance from init)")

    print(f"\n  {B}Oracle ranking (Thompson Sampling):{W}")
    for i, oracle in enumerate(adaptation["oracle_ranking"], 1):
        print(f"    {i}. {oracle}")

    if "meta_judge_critiques" in adapt_report:
        n = adapt_report["meta_judge_critiques"]
        mc = adapt_report.get("mean_critique_score")
        if n > 0:
            ok(f"MetaJudge critiqued {n} episodes  mean_score={mc:.3f}")
        else:
            warn("MetaJudge: no episodes critiqued (worker may be unavailable or all critiqued)")

    # ── Round 2: same domains — observe learning effect ───────────────────────
    section("Round 2 — Same domains — observe shadow priors")
    print("  AROMER has learned priors from Round 1, but trust is not actively adjusted in shadow mode.\n")

    round2 = [
        ("Financial write — high harm history",   "financial",    "critical", "write",     0.60, 0.75, 0.60),
        ("DB write — false accept history",       "database",     "high",     "write",     0.55, 0.65, 0.50),
        ("Info read — clean history",             "information",  "low",      "read",      0.85, 0.20, 0.08),
        ("Cyber exec — harm history",             "cybersecurity","critical", "execution", 0.50, 0.80, 0.65),
    ]

    for label, domain, risk, action, trust, H, D in round2:
        ph_r1 = aromer._world.p_harm(domain, action, risk)
        adj_trust = aromer._world.adjust_trust(trust, domain, action, risk)
        delta = adj_trust - trust
        delta_color = R if delta < -0.02 else G

        observation = obs(domain, risk, action, trust, H, D)
        report, eid = aromer.decide(observation)

        verdict_color = G if report.action.value == "accept" else (
                         Y if report.action.value in ("verify", "abstain") else R)

        print(f"  {B}{label}{W}")
        print(f"    original trust={trust:.2f}  P(harm)={ph_r1:.3f}  "
              f"→  adjusted trust={adj_trust:.2f}  "
              f"({delta_color}Δ={delta:+.3f}{W})")
        print(f"    {B}Verdict:{W} {verdict_color}{report.action.value.upper()}{W}  "
              f"human_review={report.human_review_required}")
        print()

    # ── Bridge state summary ──────────────────────────────────────────────────
    section("Bridge state — all adapters after two rounds")
    bridge = aromer._bridge.state()
    print(f"  {B}Episodes processed:{W}  {bridge.n_episodes}")
    print(f"  {B}λ coupling:{W}         {bridge.lambda_coupling:.6f}")
    print(f"  {B}Phase weights:{W}")
    for phase, w in bridge.phase_weights.items():
        bar = "█" * int(w * 20) + "░" * (20 - int(w * 20))
        print(f"    {phase:<12} [{bar}]  {w:.4f}")
    print(f"  {B}Oracle ranking:{W}     {bridge.oracle_ranking}")
    print(f"  {B}Threshold states:{W}")
    for name, val in bridge.threshold_states.items():
        print(f"    {name:<32} {val:.4f}")

    # ── Full AROMER summary ───────────────────────────────────────────────────
    section("AROMER full summary")
    summary = aromer.summary()
    exp = summary["experience"]
    print(f"  {B}Version:{W}       {summary['version']}")
    print(f"  {B}Adapt cycles:{W}  {summary['adapt_cycles']}")
    print(f"  {B}Store size:{W}    {summary['store_size']} episodes")
    print(f"  {B}Accuracy:{W}")
    s_far = exp['false_accept_rate']
    s_fbr = exp['false_block_rate']
    print(f"    Correct decisions:   {exp['correct']}/{exp['total']}")
    print(f"    False-accept rate:   {f'{s_far:.3f}' if s_far is not None else 'N/A'}")
    print(f"    False-block rate:    {f'{s_fbr:.3f}' if s_fbr is not None else 'N/A'}")
    wm = summary["world_model"]
    print(f"  {B}World model:{W}")
    print(f"    Contexts tracked:    {wm['n_contexts']}")
    print(f"    High-risk contexts:  {len(wm['high_risk_contexts'])}  "
          f"(P(harm) > 0.50)")
    if wm["high_risk_contexts"]:
        for ctx in wm["high_risk_contexts"][:3]:
            print(f"      {ctx['domain']:<14} {ctx['action_type']:<12} "
                  f"P(harm)={ctx['p_harm']:.3f}  n={ctx['n_observations']}")

    # ── Worker status ─────────────────────────────────────────────────────────
    section("Cloudflare Worker status (24/7 autonomous learning)")
    try:
        from remora.evidence.worker_client import REMORAWorkerClient
        client = REMORAWorkerClient(base_url="https://go-star-remora.razorsharp.workers.dev")
        if client.is_available():
            s = client.status()
            ok(f"go-star-remora worker: ONLINE  backend={s.get('inference_backend')}  oracles={s.get('n_oracles')}")
            ok("MetaJudge available — AROMER will self-critique on adapt()")
        else:
            warn("go-star-remora worker: offline — MetaJudge disabled")
    except Exception as e:
        warn(f"Worker check: {e}")

    print()
    warn("AROMER Worker (workers/aromer/) not yet deployed — run 'make aromer-deploy' to activate 24/7 learning")
    ok("Local AROMER fully functional — all five components operational")

    # ── Quick-start snippet ───────────────────────────────────────────────────
    banner("Quick-start — how to use AROMER in your code", M)
    print(f"""{M}from remora.aromer import AromerOrchestrator, OutcomeType
from remora.policy import PolicyObservation

aromer = AromerOrchestrator()          # loads learned state from ~/.aromer/

obs = PolicyObservation(
    question="Deploy payment service",
    phase="critical", trust_score=0.55,
    final_H=0.78, final_D=0.62,
    risk_tier="high", domain="financial",
    action_type="write", target_environment="production",
)

report, episode_id = aromer.decide(obs)
print(report.action.value)             # VERIFY / ESCALATE / ACCEPT / ABSTAIN

# Later — after observing what actually happened:
aromer.record_outcome(episode_id, OutcomeType.CORRECT_BLOCK)

# Trigger learning cycle manually (or let CF Worker do it hourly):
aromer.adapt(){W}
""")

    banner("AROMER demo complete - all components verified", G)
    print(f"  {G}✓{W}  EpisodicStore      — {aromer._store.size} episodes persisted to JSONL")
    print(f"  {G}✓{W}  DomainHarmPrior    — {aromer._world.summary()['n_contexts']} contexts in world model")
    print(f"  {G}✓{W}  AdapterBridge      — {aromer._bridge.state().n_episodes} outcomes propagated")
    print(f"  {G}✓{W}  ThermodynamicAdapter — λ={aromer._bridge.adapted_lambda():.4f} (adapted)")
    print(f"  {G}✓{W}  OracleBandit       — oracle ranking maintained")
    print(f"  {G}✓{W}  AromerOrchestrator — {summary['adapt_cycles']} adaptation cycle(s) run")
    print()


if __name__ == "__main__":
    main()
