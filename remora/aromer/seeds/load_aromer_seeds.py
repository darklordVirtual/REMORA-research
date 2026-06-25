#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER Seed Loader — bootstrap world model and episodic store from pre-seeded priors.

IMPORTANT: Preseed ≠ truth. Seeds are hypotheses with provenance, weight, confidence
and decay — not ground truth. AROMER should A/B compare cold-start vs. preseeded.

Usage
-----
    # Dry run — validate and report what would be imported
    python remora/aromer/seeds/load_aromer_seeds.py --seed-dir remora/aromer/seeds --dry-run

    # Import to default paths (~/.aromer/)
    python remora/aromer/seeds/load_aromer_seeds.py --seed-dir remora/aromer/seeds

    # Import to custom paths and write artifact
    python remora/aromer/seeds/load_aromer_seeds.py \\
        --seed-dir remora/aromer/seeds \\
        --world-model-path .aromer/world_model.json \\
        --episodes-path .aromer/episodes.jsonl \\
        --out artifacts/aromer_seed_import.json

    # Shadow mode: compute adjustments without committing
    python remora/aromer/seeds/load_aromer_seeds.py --seed-dir remora/aromer/seeds --shadow

Seed files processed (in order):
  Tool-risk pack v0.1:
    01_invariants.seed.json              — safety invariants
    02_tool_risk_ontology.seed.json      — tool risk classifications
    03_domain_priors.seed.json           — Bayesian domain harm priors → DomainHarmPrior
    04_agentharm_lessons.seed.json       — AgentHarm lessons
    05_known_failure_patterns.seed.json  — known failure patterns
    06_epistemic_rules.seed.json         — epistemic rules
    07_strategy_patterns.seed.json       — strategy patterns
    08_telecom_network_ops.seed.json     — telecom domain lessons
    09_cloudflare_github_ops.seed.json   — CF/GitHub domain lessons
    10_golden_episodes.seed.jsonl        — golden episodes → EpisodicStore

  Cognitive foundation pack v0.2:
    11_cognitive_primitives.seed.json    — goal/uncertainty/risk/belief/attention/next-step primitives
    12_epistemic_foundation.seed.json    — verified/plausible/unknown/contradiction/calibration
    13_error_taxonomy.seed.json          — hallucination/partial_truth/overgeneralization/false_causality/bias
    14_causal_reasoning.seed.json        — causality levels, counterfactuals, interventions
    15_planning.seed.json                — reversible-first, simulate-before-act, stop conditions
    16_memory_architecture.seed.json     — episodic/semantic/causal/skill/failure/consolidation
    17_self_model.seed.json              — capability bounds, calibration, limitations, bias
    18_learning_laws.seed.json           — curated-only, positive-gain, safety-immutable, slow-updates
    19_transfer_rules.seed.json          — pattern-over-phrase, boundary conditions, replay-before-compress
    20_domain_capsules.seed.json         — database/medical/infrastructure/agentic/financial capsules
    21_eval_gates.seed.json              — A/B gate, contradiction gate, autonomy gate, regression gate
    22_golden_cognitive_episodes.seed.jsonl — 6 golden cognitive episodes → EpisodicStore
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Allow running from workspace root without install
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SeedImportReport:
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    seed_dir: str = ""
    dry_run: bool = False
    shadow_mode: bool = False

    # Counts
    files_processed: int = 0
    total_entries: int = 0
    domain_priors_loaded: int = 0
    golden_episodes_loaded: int = 0
    metadata_entries: int = 0
    skipped_entries: int = 0
    errors: list[str] = field(default_factory=list)

    # Detail
    domain_prior_keys: list[str] = field(default_factory=list)
    golden_episode_ids: list[str] = field(default_factory=list)
    invariant_ids: list[str] = field(default_factory=list)
    lesson_ids: list[str] = field(default_factory=list)
    failure_pattern_ids: list[str] = field(default_factory=list)
    epistemic_rule_ids: list[str] = field(default_factory=list)
    strategy_pattern_ids: list[str] = field(default_factory=list)

    # Cognitive foundation v0.2 tracking
    cognitive_primitive_ids: list[str] = field(default_factory=list)
    epistemic_foundation_ids: list[str] = field(default_factory=list)
    error_taxonomy_ids: list[str] = field(default_factory=list)
    causal_reasoning_ids: list[str] = field(default_factory=list)
    planning_ids: list[str] = field(default_factory=list)
    memory_architecture_ids: list[str] = field(default_factory=list)
    self_model_ids: list[str] = field(default_factory=list)
    learning_law_ids: list[str] = field(default_factory=list)
    transfer_rule_ids: list[str] = field(default_factory=list)
    domain_capsule_ids: list[str] = field(default_factory=list)
    eval_gate_ids: list[str] = field(default_factory=list)

    finished_at: str = ""
    status: str = "pending"

    def finish(self, status: str = "ok") -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["summary"] = {
            "domain_priors": self.domain_priors_loaded,
            "golden_episodes": self.golden_episodes_loaded,
            "metadata_only": self.metadata_entries,
            "errors": len(self.errors),
            "tool_risk_pack_v0_1": {
                "invariants": len(self.invariant_ids),
                "epistemic_rules": len(self.epistemic_rule_ids),
                "strategy_patterns": len(self.strategy_pattern_ids),
                "lessons": len(self.lesson_ids),
                "failure_patterns": len(self.failure_pattern_ids),
            },
            "cognitive_foundation_pack_v0_2": {
                "cognitive_primitives": len(self.cognitive_primitive_ids),
                "epistemic_foundations": len(self.epistemic_foundation_ids),
                "error_taxonomy": len(self.error_taxonomy_ids),
                "causal_reasoning": len(self.causal_reasoning_ids),
                "planning": len(self.planning_ids),
                "memory_architecture": len(self.memory_architecture_ids),
                "self_model": len(self.self_model_ids),
                "learning_laws": len(self.learning_law_ids),
                "transfer_rules": len(self.transfer_rule_ids),
                "domain_capsules": len(self.domain_capsule_ids),
                "eval_gates": len(self.eval_gate_ids),
            },
        }
        return d


# ---------------------------------------------------------------------------
# Domain prior injection
# ---------------------------------------------------------------------------

def _compute_alpha_beta(p_harm: float, n_pseudo: int) -> tuple[float, float]:
    """Convert (p_harm_prior, n_pseudo_observations) to Beta(alpha, beta) params.

    Starts from a uniform prior Beta(1, 1) and injects n_pseudo pseudo-observations.
    alpha = 1 + n_pseudo * p_harm
    beta  = 1 + n_pseudo * (1 - p_harm)
    """
    alpha = 1.0 + n_pseudo * p_harm
    beta  = 1.0 + n_pseudo * (1.0 - p_harm)
    return round(alpha, 4), round(beta, 4)


def _inject_domain_prior(
    world_model_data: dict[str, dict[str, float]],
    domain: str,
    action_type: str,
    risk_tier: str,
    p_harm_prior: float,
    n_pseudo: int,
    weight: float,
    report: SeedImportReport,
    *,
    overwrite: bool = False,
) -> None:
    """Inject a domain prior into the world model dict."""
    key = f"{domain}:{action_type}:{risk_tier}"
    alpha, beta = _compute_alpha_beta(p_harm_prior, n_pseudo)

    # Scale by weight: reduce pseudo-observations proportionally
    effective_n = n_pseudo * weight
    alpha, beta = _compute_alpha_beta(p_harm_prior, int(effective_n))

    if key in world_model_data and not overwrite:
        # Merge: average the pseudo-observations (don't double-count)
        existing = world_model_data[key]
        world_model_data[key] = {
            "alpha": round((existing["alpha"] + alpha) / 2, 4),
            "beta":  round((existing["beta"]  + beta)  / 2, 4),
        }
    else:
        world_model_data[key] = {"alpha": alpha, "beta": beta}

    report.domain_prior_keys.append(key)
    report.domain_priors_loaded += 1


# ---------------------------------------------------------------------------
# Seed file processors
# ---------------------------------------------------------------------------

def _process_domain_prior_entry(
    entry: dict[str, Any],
    world_model_data: dict[str, dict[str, float]],
    report: SeedImportReport,
    dry_run: bool,
) -> None:
    p = entry.get("payload", {})
    required = ["domain", "action_type", "risk_tier", "p_harm_prior", "n_pseudo_observations"]
    for f in required:
        if f not in p:
            report.errors.append(f"[{entry.get('id','?')}] Missing payload field: {f}")
            report.skipped_entries += 1
            return

    if not dry_run:
        _inject_domain_prior(
            world_model_data,
            domain=p["domain"],
            action_type=p["action_type"],
            risk_tier=p["risk_tier"],
            p_harm_prior=p["p_harm_prior"],
            n_pseudo=p["n_pseudo_observations"],
            weight=entry.get("weight", 1.0),
            report=report,
        )
    else:
        key = f"{p['domain']}:{p['action_type']}:{p['risk_tier']}"
        report.domain_prior_keys.append(key)
        report.domain_priors_loaded += 1


def _lesson_like_to_domain_prior(
    entry: dict[str, Any],
    world_model_data: dict[str, dict[str, float]],
    report: SeedImportReport,
    dry_run: bool,
) -> None:
    """Derive a domain prior from a lesson/domain_lesson entry's correct_verdict."""
    p = entry.get("payload", {})
    domain = p.get("domain")
    risk_tier = p.get("risk_tier")
    correct_verdict = p.get("correct_verdict", "")

    if not domain or not risk_tier:
        return  # no domain info — only metadata

    # Infer action_type from tool_risk entries, else use 'execution' as default
    action_type = p.get("action_type", "execution")

    # Infer p_harm from correct_verdict
    verdict_to_p_harm = {
        "escalate": 0.85,
        "verify":   0.55,
        "abstain":  0.50,
        "accept":   0.10,
    }
    p_harm = verdict_to_p_harm.get(correct_verdict, 0.50)

    # Low pseudo-observations for lessons (less direct than domain_prior entries)
    n_pseudo = 5

    if not dry_run:
        _inject_domain_prior(
            world_model_data,
            domain=domain,
            action_type=action_type,
            risk_tier=risk_tier,
            p_harm_prior=p_harm,
            n_pseudo=n_pseudo,
            weight=entry.get("weight", 0.7) * 0.5,  # halved weight for indirect evidence
            report=report,
        )
    else:
        key = f"{domain}:{action_type}:{risk_tier}"
        if key not in report.domain_prior_keys:
            report.domain_prior_keys.append(key)
            report.domain_priors_loaded += 1


def _domain_capsule_to_priors(
    entry: dict[str, Any],
    world_model_data: dict[str, dict[str, float]],
    report: SeedImportReport,
    dry_run: bool,
) -> None:
    """Extract domain harm priors from a domain_capsule's risk_taxonomy."""
    p = entry.get("payload", {})
    domain = p.get("domain")
    if not domain:
        return

    risk_taxonomy = p.get("risk_taxonomy", {})
    p_harm_table = p.get("p_harm_priors", {})
    weight = entry.get("weight", 0.85)

    for action_type, spec in risk_taxonomy.items():
        risk_tier = spec.get("risk_tier", "medium")
        lookup_key = f"{action_type}:{risk_tier}"
        p_harm = p_harm_table.get(lookup_key, None)
        if p_harm is None:
            # Derive from verdict
            verdict_to_p = {"escalate": 0.85, "verify": 0.55, "accept": 0.10, "abstain": 0.50}
            p_harm = verdict_to_p.get(spec.get("verdict", "accept"), 0.40)
        n_pseudo = 8  # domain capsules: moderate pseudo-observations
        if not dry_run:
            _inject_domain_prior(
                world_model_data,
                domain=domain,
                action_type=action_type,
                risk_tier=risk_tier,
                p_harm_prior=p_harm,
                n_pseudo=n_pseudo,
                weight=weight,
                report=report,
            )
        else:
            key = f"{domain}:{action_type}:{risk_tier}"
            if key not in report.domain_prior_keys:
                report.domain_prior_keys.append(key)
                report.domain_priors_loaded += 1


def _process_seed_file(
    path: Path,
    world_model_data: dict[str, dict[str, float]],
    report: SeedImportReport,
    dry_run: bool,
) -> list[dict[str, Any]]:
    """Load and process a .seed.json file. Returns list of entries."""
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        report.errors.append(f"[{path.name}] Failed to parse: {e}")
        return []

    if not isinstance(entries, list):
        report.errors.append(f"[{path.name}] Expected a JSON array at root")
        return []

    for entry in entries:
        etype = entry.get("type", "")
        eid = entry.get("id", "?")

        if etype == "domain_prior":
            _process_domain_prior_entry(entry, world_model_data, report, dry_run)

        elif etype in ("lesson", "domain_lesson", "failure_pattern"):
            # Lessons contribute weak domain priors + metadata
            _lesson_like_to_domain_prior(entry, world_model_data, report, dry_run)
            if etype in ("lesson", "domain_lesson"):
                report.lesson_ids.append(eid)
            else:
                report.failure_pattern_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "tool_risk":
            # Tool risk entries contribute weak domain priors
            _lesson_like_to_domain_prior(entry, world_model_data, report, dry_run)
            report.metadata_entries += 1

        elif etype == "safety_invariant":
            report.invariant_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "epistemic_rule":
            report.epistemic_rule_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "strategy_pattern":
            report.strategy_pattern_ids.append(eid)
            report.metadata_entries += 1

        # ---- Cognitive foundation v0.2 types ----
        elif etype == "cognitive_primitive":
            report.cognitive_primitive_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "epistemic_foundation":
            report.epistemic_foundation_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "error_taxonomy":
            report.error_taxonomy_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "causal_reasoning":
            report.causal_reasoning_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "planning":
            report.planning_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "memory_architecture":
            report.memory_architecture_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "self_model":
            report.self_model_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "learning_law":
            report.learning_law_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "transfer_rule":
            report.transfer_rule_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "domain_capsule":
            # Domain capsules contribute priors from their risk_taxonomy
            _domain_capsule_to_priors(entry, world_model_data, report, dry_run)
            report.domain_capsule_ids.append(eid)
            report.metadata_entries += 1

        elif etype == "eval_gate":
            report.eval_gate_ids.append(eid)
            report.metadata_entries += 1

        else:
            report.skipped_entries += 1
            report.errors.append(f"[{eid}] Unknown seed type: '{etype}'")

        report.total_entries += 1

    report.files_processed += 1
    return entries


def _process_golden_episodes(
    path: Path,
    report: SeedImportReport,
    dry_run: bool,
    episodes_path: Path | None,
) -> None:
    """Load golden episodes from JSONL and append to EpisodicStore JSONL."""
    try:
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception as e:
        report.errors.append(f"[{path.name}] Failed to read: {e}")
        return

    episodes = []
    for i, line in enumerate(lines, 1):
        try:
            ep = json.loads(line)
            episodes.append(ep)
        except Exception as e:
            report.errors.append(f"[{path.name}:{i}] Invalid JSON: {e}")

    if dry_run:
        for ep in episodes:
            eid = ep.get("episode_id", f"golden-{len(report.golden_episode_ids)+1}")
            report.golden_episode_ids.append(eid)
            report.golden_episodes_loaded += 1
        report.files_processed += 1
        return

    if episodes_path is None:
        # Use default path
        from pathlib import Path as _P
        episodes_path = _P.home() / ".aromer" / "episodes.jsonl"

    episodes_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing episode IDs to avoid duplicates
    existing_ids: set[str] = set()
    if episodes_path.exists():
        for line in episodes_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    ep = json.loads(line)
                    existing_ids.add(ep.get("episode_id", ""))
                except Exception:
                    pass

    appended = 0
    with episodes_path.open("a", encoding="utf-8") as fh:
        for ep in episodes:
            eid = ep.get("episode_id", "")
            if eid in existing_ids:
                report.skipped_entries += 1
                continue
            fh.write(json.dumps(ep, ensure_ascii=False) + "\n")
            report.golden_episode_ids.append(eid)
            report.golden_episodes_loaded += 1
            appended += 1

    report.files_processed += 1
    report.total_entries += len(episodes)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_seeds(
    seed_dir: str | Path,
    *,
    world_model_path: str | Path | None = None,
    episodes_path: str | Path | None = None,
    dry_run: bool = False,
    shadow_mode: bool = False,
    out: str | Path | None = None,
    verbose: bool = True,
) -> SeedImportReport:
    """Load all seed files from seed_dir into AROMER world model and episodic store.

    Parameters
    ----------
    seed_dir:          Directory containing seed files.
    world_model_path:  Path for DomainHarmPrior JSON. Default: ~/.aromer/world_model.json
    episodes_path:     Path for EpisodicStore JSONL. Default: ~/.aromer/episodes.jsonl
    dry_run:           Validate and report without writing.
    shadow_mode:       Compute but do not commit world model changes (monitoring only).
    out:               If set, write the import report JSON to this path.
    verbose:           Print progress to stdout.
    """
    seed_dir = Path(seed_dir)
    if not seed_dir.exists():
        raise FileNotFoundError(f"Seed directory not found: {seed_dir}")

    report = SeedImportReport(
        seed_dir=str(seed_dir),
        dry_run=dry_run,
        shadow_mode=shadow_mode,
    )

    # Load existing world model (will be merged into)
    if world_model_path is not None:
        wm_path = Path(world_model_path)
    else:
        wm_path = Path.home() / ".aromer" / "world_model.json"

    world_model_data: dict[str, dict[str, float]] = {}
    if wm_path.exists():
        try:
            world_model_data = json.loads(wm_path.read_text(encoding="utf-8"))
            if verbose:
                print(f"[seed-loader] Loaded existing world model: {len(world_model_data)} keys from {wm_path}")
        except Exception as e:
            report.errors.append(f"Failed to load existing world model: {e}")

    # Seed files to process (in order)
    seed_files = [
        # Tool-risk pack v0.1
        "01_invariants.seed.json",
        "02_tool_risk_ontology.seed.json",
        "03_domain_priors.seed.json",
        "04_agentharm_lessons.seed.json",
        "05_known_failure_patterns.seed.json",
        "06_epistemic_rules.seed.json",
        "07_strategy_patterns.seed.json",
        "08_telecom_network_ops.seed.json",
        "09_cloudflare_github_ops.seed.json",
        # Cognitive foundation pack v0.2
        "11_cognitive_primitives.seed.json",
        "12_epistemic_foundation.seed.json",
        "13_error_taxonomy.seed.json",
        "14_causal_reasoning.seed.json",
        "15_planning.seed.json",
        "16_memory_architecture.seed.json",
        "17_self_model.seed.json",
        "18_learning_laws.seed.json",
        "19_transfer_rules.seed.json",
        "20_domain_capsules.seed.json",
        "21_eval_gates.seed.json",
        # Benign medium-risk coding session contexts (friction reduction pack v0.3)
        "23_coding_session_ops.seed.json",
    ]

    for fname in seed_files:
        fpath = seed_dir / fname
        if not fpath.exists():
            report.errors.append(f"Seed file not found: {fname}")
            continue
        if verbose:
            print(f"[seed-loader] Processing {fname} ...")
        _process_seed_file(fpath, world_model_data, report, dry_run or shadow_mode)

    # Golden episodes — v0.1 tool-risk pack
    ep_file = seed_dir / "10_golden_episodes.seed.jsonl"
    if ep_file.exists():
        if verbose:
            print("[seed-loader] Processing 10_golden_episodes.seed.jsonl ...")
        _process_golden_episodes(
            ep_file,
            report,
            dry_run or shadow_mode,
            Path(episodes_path) if episodes_path else None,
        )
    else:
        report.errors.append("Golden episodes file not found: 10_golden_episodes.seed.jsonl")

    # Golden episodes — v0.2 cognitive pack
    cog_ep_file = seed_dir / "22_golden_cognitive_episodes.seed.jsonl"
    if cog_ep_file.exists():
        if verbose:
            print("[seed-loader] Processing 22_golden_cognitive_episodes.seed.jsonl ...")
        _process_golden_episodes(
            cog_ep_file,
            report,
            dry_run or shadow_mode,
            Path(episodes_path) if episodes_path else None,
        )
    else:
        report.errors.append("Cognitive golden episodes file not found: 22_golden_cognitive_episodes.seed.jsonl")

    # Commit world model
    if not dry_run and not shadow_mode:
        wm_path.parent.mkdir(parents=True, exist_ok=True)
        wm_path.write_text(json.dumps(world_model_data, indent=2), encoding="utf-8")
        if verbose:
            print(f"[seed-loader] World model written: {len(world_model_data)} keys → {wm_path}")
    elif shadow_mode and verbose:
        print(f"[seed-loader] Shadow mode: world model NOT written ({len(world_model_data)} keys computed)")
    elif dry_run and verbose:
        print(f"[seed-loader] Dry run: world model NOT written ({len(world_model_data)} keys computed)")

    # Write report artifact
    report.finish(status="ok" if not report.errors else "ok_with_warnings")
    if out is not None:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        if verbose:
            print(f"[seed-loader] Report written → {out_path}")

    return report


def _print_summary(report: SeedImportReport) -> None:
    s = report
    print()
    print("═" * 60)
    print("  AROMER Seed Import Report")
    print("═" * 60)
    print(f"  Status:            {s.status}")
    print(f"  Dry run:           {s.dry_run}")
    print(f"  Shadow mode:       {s.shadow_mode}")
    print(f"  Files processed:   {s.files_processed}")
    print(f"  Total entries:     {s.total_entries}")
    print(f"  Domain priors:     {s.domain_priors_loaded}")
    print(f"  Golden episodes:   {s.golden_episodes_loaded}")
    print(f"  Metadata entries:  {s.metadata_entries}")
    print(f"  Skipped:           {s.skipped_entries}")
    print(f"  Errors/warnings:   {len(s.errors)}")
    if s.errors:
        print()
        print("  Warnings / Errors:")
        for e in s.errors:
            print(f"    ⚠  {e}")
    print()
    print("  -- Tool-risk pack v0.1 --")
    print("  Safety invariants:", len(s.invariant_ids))
    print("  Epistemic rules:  ", len(s.epistemic_rule_ids))
    print("  Strategy patterns:", len(s.strategy_pattern_ids))
    print("  Lessons loaded:   ", len(s.lesson_ids))
    print("  Failure patterns: ", len(s.failure_pattern_ids))
    print()
    print("  -- Cognitive foundation pack v0.2 --")
    print("  Cognitive primitives:", len(s.cognitive_primitive_ids))
    print("  Epistemic foundations:", len(s.epistemic_foundation_ids))
    print("  Error taxonomy:      ", len(s.error_taxonomy_ids))
    print("  Causal reasoning:    ", len(s.causal_reasoning_ids))
    print("  Planning rules:      ", len(s.planning_ids))
    print("  Memory architecture: ", len(s.memory_architecture_ids))
    print("  Self-model:          ", len(s.self_model_ids))
    print("  Learning laws:       ", len(s.learning_law_ids))
    print("  Transfer rules:      ", len(s.transfer_rule_ids))
    print("  Domain capsules:     ", len(s.domain_capsule_ids))
    print("  Eval gates:          ", len(s.eval_gate_ids))
    print()
    print("  NOTE: Preseed ≠ truth. Run AROMER in shadow mode first and")
    print("  compare cold-start vs. preseeded on the same episode replay set.")
    print()
    print("  Recommended experiment:")
    print("    A: cold-start AROMER")
    print("    B: tool-risk seeded")
    print("    C: tool-risk + cognitive seeded")
    print("  Measure at 100 / 500 / 1000 episodes.")
    print("═" * 60)


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Load AROMER seed pack into world model and episodic store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--seed-dir", default="remora/aromer/seeds",
        help="Directory containing seed files (default: remora/aromer/seeds)",
    )
    parser.add_argument(
        "--world-model-path", default=None,
        help="Path for world model JSON (default: ~/.aromer/world_model.json)",
    )
    parser.add_argument(
        "--episodes-path", default=None,
        help="Path for episodic store JSONL (default: ~/.aromer/episodes.jsonl)",
    )
    parser.add_argument(
        "--out", default=None,
        help="Write import report JSON to this path",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate and report without writing any files",
    )
    parser.add_argument(
        "--shadow", action="store_true",
        help="Compute adjustments without committing to world model",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress progress output",
    )
    args = parser.parse_args()

    report = load_seeds(
        seed_dir=args.seed_dir,
        world_model_path=args.world_model_path,
        episodes_path=args.episodes_path,
        dry_run=args.dry_run,
        shadow_mode=args.shadow,
        out=args.out,
        verbose=not args.quiet,
    )

    _print_summary(report)

    return 0 if report.status in ("ok", "ok_with_warnings") else 1


if __name__ == "__main__":
    sys.exit(_main())
