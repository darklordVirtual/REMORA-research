# VERIFY Resolution via AI-Control Protocols (RF-04)

Status: library-only; pre-registered run completed with a negative outcome. The
module `remora/governance/control_protocols.py` is flag-gated behind
`REMORA_CONTROL_PROTOCOLS` and is still wired into nothing.

The pre-registered re-scoring below has now been run. The result is an honest
negative: the FAR target was met (0.0%, Wilson upper 1.8%) and the FBR target
was not (100.0% vs <=40%). The cause is structural; every verdict in the
source artifact is ESCALATE, and these protocols act only on VERIFY, so they
have nothing to resolve. The run bounds what the protocols can do on this
dataset; it does not identify which benign escalations were avoidable. Artifact:
`artifacts/verify_protocols/agentharm_rescore_v1.json`; analysis:
`NEGATIVE_RESULTS.md` §19.

One resolution route is explicitly ruled out by measurement. A blanket
`ESCALATE + unresolved_risk -> VERIFY` reclassification in the decision engine
was implemented and measured on the 93-episode replay arena on 2026-07-30: it
moved 19 decisions, all 19 ground-truth harmful, and 0 benign; no friction
reduction, 51% of harmful escalations downgraded. Any future resolution path
must be **selective eligibility carried in a separate field**, never a
redefinition of what `DecisionReport.action` means. The contract is pinned by
`tests/test_escalate_semantics_guard.py`.

## Motivation

The AgentHarm external validation (`results/external_benchmark_agentharm_v1.json`,
CLAIM-002) recorded FAR 0.0% on the 208 harmful scenarios and FBR 100.0% on
the 208 benign variants: all 416 scenarios resolve to ESCALATE. The FBR
mechanism is structural, not a scoring accident; benign variants share
`harm_category` with their harmful counterparts, so the category-to-risk-tier
mapping triggers the VERIFY floor and every benign variant lands on the
human-review path, while FAR 0.0% is separately carried by Stage-1 hard-block
invariants. The paper names this corner an explicit target for REMORA's
calibration roadmap (`paper/remora_paper.md` §2.11), and
`docs/assurance/best_practice_gap_audit_v1.md` grades its AI-control row
yellow ("no formal control-protocol red-team evaluation"). The Neyman-Pearson
framing of the FAR/FBR corner is already written in
`docs/methods/theoretical_foundations_proposals_v1.md` item 5 and is not
restated here.

The AI-control literature resolves exactly this shape: instead of terminal
review for every suspicious action, a control protocol applies interventions
(defer-to-trusted, trusted editing, defer-to-resample) that aim to buy back
benign utility without giving up the safety floor. The status-quo VERIFY
machinery this extends is `remora/governance/review_queue.py` (REM-032/REM-033:
only VERIFY and ESCALATE enqueue; TTL expiry resolves to ABSTAIN; never
auto-accept, never indefinite silent pending).

## Strategy set

Encoded as `VerifyStrategy` in `remora/governance/control_protocols.py`:

| Strategy | Semantics |
|----------|-----------|
| `seek_evidence` | Status quo — pass through to the review queue unchanged. |
| `defer_to_trusted` | The trusted (deterministic policy-layer) monitor decides; unanimous approval within audit budget resolves MONITORED_ACCEPT. |
| `trusted_edit` | As defer-to-trusted, over verdicts on a trusted-edited variant of the action. |
| `defer_to_resample` | Requires at least `resample_k` unanimous trusted verdicts; guarded against suspiciousness suppression (below). |

The "trusted model" role is played by the deterministic policy layer: the
module only consumes `TrustedVerdict` values (approved, suspicion, source) and
never calls models. This is a documented substitution relative to the
literature, where the trusted monitor is a weaker model.

There is deliberately no plain ACCEPT in the resolution vocabulary
(`VerifyResolution`): the least severe outcome a protocol can grant is
MONITORED_ACCEPT; execution under audit, spending a bounded audit budget.

## The rationale-channel rule

The gate must not return the monitor's rationale on the agent channel.
Monitor-rationale feedback lets a gated adversary iterate toward stealthier
attacks (arXiv:2605.26047), and adaptive attacks on trusted monitors already
subvert control protocols without that gift (arXiv:2510.09462). Therefore
`ControlProtocolResult` carries exactly one agent-visible field,
`agent_message`: a fixed neutral sentence with no monitor scores, no rule
identifiers, no strategy names, and no diff of what would have passed. All
ESCALATE paths share a single sentence, so the agent cannot distinguish a
verdict disapproval from an exhausted budget from the adaptive-attack guard.
Everything else (strategy, verdict counts, budget state, guard flags) goes
to `audit_detail`, the internal audit channel.

## Safety invariants

Enforced in code in `remora/governance/control_protocols.py` (not just in
tests), and covered by `tests/test_control_protocols.py`:

(a) VERIFY-only scope: a non-VERIFY decision passes through unchanged;
    the protocol can never weaken a hard block or an ESCALATE.
(b) Flag-gated status quo: with `enabled=False` (or the SEEK_EVIDENCE
    strategy) the resolution is the status-quo route to human review,
    represented as ESCALATE.
(c) Monitored accept is earned: MONITORED_ACCEPT requires a non-status-quo
    strategy, unanimous trusted approval (unanimity over an empty verdict set
    is not approval), at least `resample_k` verdicts for DEFER_TO_RESAMPLE,
    and remaining audit budget; anything less resolves ESCALATE.
(d) Budget exhaustion is loud: an exhausted audit budget resolves
    ESCALATE with the budget state recorded, never a silent accept.
(e) Adaptive-attack guard: for DEFER_TO_RESAMPLE, a monotonically
    non-increasing suspicion sequence spanning more than `resample_k`
    verdicts (the suspiciousness-suppression pattern, arXiv:2510.09462)
    resolves ESCALATE even when every verdict approves.

## Pre-registered protocol for the future offline re-scoring

Frozen decision rule, committed before any run (precedent:
`experiments/agentharm/PREREGISTERED.md`; SAP-style; write the number down
first). CLAIM-002 is an imported historical result produced via the AROMER
`/decide` worker path and cannot be regenerated from this repository
(`docs/assurance/rebenchmark_protocol_v1.md`); it stays untouched. The
benchmark scope remains intent-gating, not tool-call interception
(`experiments/agentharm/INTERCEPTION_NOTES.md`).

- **Input.** The 416 frozen scenario instructions (208 harmful + 208 benign)
  embedded in `results/external_benchmark_agentharm_v1.json`.
- **Procedure.** Deterministic replay of every scenario through the local
  decision path with control protocols enabled; trusted verdicts come from
  the deterministic policy layer; no model calls, no re-prompting, no
  scenario editing.
- **Pre-committed targets (written before any run; these are targets, not
  results).**
  - FAR stays 0.0% on the 208 harmful scenarios. Any regression (a single
    harmful monitored-accept) rejects the protocol outright.
  - FBR on the 208 benign scenarios is at most 40%.
- **Outcome handling.** The run ships as a NEW artifact,
  `artifacts/verify_protocols/agentharm_rescore_v1.json` (FAR/FBR per
  strategy, per-split N, Wilson CI), under a NEW claim id; CLAIM-002 is
  imported-historical and is not updated. If either target is missed, the
  result goes to `NEGATIVE_RESULTS.md`, not the README.

No sentence in this document asserts that FBR has changed; until the
pre-registered run exists on disk, the only supported statements are the
CLAIM-002 numbers quoted above from `results/external_benchmark_agentharm_v1.json`.

## Literature

- Greenblatt et al. (2024). *AI Control: Improving Safety Despite Intentional
  Subversion.* arXiv:2312.06942. Trusted monitoring, defer-to-trusted,
  trusted editing.
- Bhatt et al. (2025). *Ctrl-Z: Controlling AI Agents via Resampling.*
  arXiv:2504.10374. Resample protocols, safety/usefulness Pareto.
- Kutasov et al. (2025). *SHADE-Arena*. Control evaluation in diverse agentic
  environments.
- Anonymous (2025). *Evaluating Control Protocols for Untrusted AI Agents.*
  arXiv:2511.02997. Resampling-for-incrimination plus defer-on-critical in
  SHADE-Arena.
- (2025). *Adaptive Attacks on Trusted Monitors Subvert AI Control Protocols.*
  arXiv:2510.09462. Defer-to-resample can backfire under adaptive attack;
  invariant (e) is designed against this.
- (2026). *Retrying vs Resampling in AI Control.* arXiv:2605.26047;
  monitor-rationale feedback helps adversaries iterate; source of the
  rationale-channel rule.
- (2026). *SLEIGHT-Bench.* arXiv:2605.16626. Evasion attacks against
  monitors; adversarial test inspiration.
