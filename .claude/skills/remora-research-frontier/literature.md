# Frontier literature for REMORA (verified 2026-10-04)

Every arXiv id below was resolved by title against the arXiv export API on
2026-10-04 and the returned title matched. Author-reported figures are not
reproduced here on purpose: quote them from the paper, labelled as the
authors' numbers, and never beside a REMORA number. "In repo" is what
`grep -ril` found on the working tree that day; re-check before relying on it.

Tiers: A changes design or evaluation now · B supports method or benchmark
· C threat model and context. Binding uses the register ids in
`register-map.md`.

## Tier A

| # | Work | arXiv | REMORA binding | In repo (2026-10-04) | Disposition |
|---|---|---|---|---|---|
| 1 | AEGIS: No Tool Call Left Unchecked (Yuan et al., 2026) | 2603.12621 | PROV-01/03/07/13/17, RF-13 | `docs/benchmarks/aegis-remora-crosswalk.md` (system crosswalk); not in the matrix bibliography, not a `PA-SRC` source | P0: add as `PA-SRC`, then `PA-REV` for the PROV rows it touches, then related work. Not a new comparison. |
| 2 | Conformal Risk Control (Angelopoulos et al., 2022) | 2208.02814 | RES-003 (`crc.py`, adaptation); `risk_control.py::crc_threshold` (direct, library) | matrix `implemented_line` | Register the two levels separately. |
| 3 | Learn then Test (Angelopoulos et al., 2021) | 2110.01052 | RES-002/003 compendium ref; `method_alternatives_2026_07.md` | docstring "LTT-style" only | Reviewed, not implemented. Do not implement to have it. |
| 4 | AI Control: Improving Safety Despite Intentional Subversion (Greenblatt et al., 2023) | 2312.06942 | RF-04, `control_protocols.py` | matrix `implemented_line`; library-only | Threat model for VERIFY; runtime adoption blocked by NR §19. |
| 5 | Ctrl-Z: Controlling AI Agents via Resampling (Bhatt et al., 2025) | 2504.10374 | RF-04 `DEFER_TO_RESAMPLE` | `code_citations` | Library-only; needs a VERIFY-bearing dataset first. |
| 6 | Retrying vs Resampling in AI Control (Lucassen & Kaufman, 2026) | 2605.26047 | RF-04 rationale-channel rule | cited in `control_protocols.py` for channel separation | Partially taken (neutral agent message). Max-suspicion protocol not adopted. |
| 7 | BashArena: A Control Setting for Highly Privileged AI Agents (Kaufman et al., 2025) | 2512.15688 | RF-09 (new adapter), RF-04 | absent | P1 falsification. First new external benchmark: privileged actions, benign utility, fixed FPR. |
| 8 | MonitoringBench: Semi-Automated Red-Teaming for Agent Monitoring (Jotautaitė et al., 2026) | 2605.09684 | RF-09, oracle robustness | absent | P1: tests monitor persuasion / refinement. |
| 9 | AgentHarm (Andriushchenko et al., 2024) | 2410.09024 | CLAIM-002, REM-014, `experiments/agentharm/`, NR §19 | evaluated; imported historical artifact | Evidence is frozen; cannot measure resolver friction. |
| 10 | FORTRESS: Frontier Risk Evaluation for National Security and Public Safety (Knight et al., 2025) | 2506.14922 | RF-09; FBR vs FAR pairing | only a string in `remora/benchmarks/sap_v3_n1200.py` | P1: adversarial prompts with benign twins measure safety and over-refusal together. |
| 11 | Prompt Injection as Role Confusion (Ye, Cui, Hadfield-Menell, 2026) | 2603.12277 | RF-06-adjacent sensor, non-authoritative | absent | Shadow test only; a style sensor never grants authority. |
| 12 | Defeating Prompt Injections by Design, CaMeL (Debenedetti et al., 2025) | 2503.18813 | RF-02, SHELF-008, `positioning_only` | taint floor, `source_spans`, `DerivationReceipt` exist | Largest mechanism gap; status PARTIAL. Write negative vectors before per-value IFC. |
| 13 | AgentLTL: A Trace-Verification Framework (Elkoussy & Perez, 2026) | 2607.02599 | RES-018, SHELF-035/036, RF-03 | absent | Audit first: can procedure contracts express before/until/never-after? Otherwise prior art. |
| 14 | Progent: Programmable Privilege Control (Shi et al., 2025) | 2504.11703 | RES-020, SHELF-009 | matrix `positioning_only` | Prior art for capability minimization; REMORA's contribution is the composition. |
| 15 | AgentSpec: Customizable Runtime Enforcement (Wang et al., 2025) | 2503.18666 | RF-03, policy invariants | matrix `positioning_only` ("near-isomorphic DSL") | No AgentSpec DSL; keep as positioning. |
| 16 | Robots That Ask For Help, KnowNo (Ren et al., 2023) | 2307.01928 | RES-002 abstain/verify routing | absent | Analogous mechanism, not the method. |
| 17 | Mitigating LLM Hallucinations via Conformal Abstention (Yadkori et al., 2024) | 2405.01563 | RES-002 | matrix `positioning_only` | Not adopted. |
| 18 | Classifier Context Rot (Martin & Roger, 2026) | 2605.12366 | RF-07, oracle evaluation | not in repo (one unrelated "Context Rot" mention) | P1 eval gap: padded-needle test for late-transcript monitor decay. |
| 19 | Distributed Attacks in Persistent-State AI Control (Hills, Caspary, Cooper Stickland, 2026) | 2607.02514 | RES-012 loop state, SHELF-006/031, NR §2/§8 | absent | P1 falsification: harm spread over individually legitimate actions. |
| 20 | AgentAbstain: Do LLM Agents Know When Not to Act? (Liu et al., 2026) | 2607.10059 | SHELF-011 `SCOPED`, RF-09 | shelf entry | Promote the adapter, not a new abstention algorithm. Tests abstention before the effect boundary. |
| 21 | Auditable Agents (Nian et al., 2026) | 2604.05485 | PROV-01, RES-009/013/017 | absent | Cheap: five-dimension auditability card with ESTABLISHED/PARTIAL/NOT_ESTABLISHED. |
| 22 | Design Patterns for Securing LLM Agents against Prompt Injections (Beurer-Kellner et al., 2025) | 2506.08837 | RF-02/10 framing | absent | Low priority; cite in related work. |
| 23 | AgentDojo (Debenedetti et al., 2024) | 2406.13352 | RF-09, SHELF-010 | adapter + pinned excerpt; matrix says `positioning_only` | Register drift: "adapter available, full benchmark not run". |

## Tier B

| # | Work | arXiv | Binding | Disposition |
|---|---|---|---|---|
| 24 | Agentic Abstention: Do Agents Know When to Stop Instead of Act? (Luo et al., 2026) | 2606.28733 | SHELF-011 neighbour | P1/P2 benchmark; abstention timing. |
| 25 | Conformal Agent Error Attribution (Feng et al., 2026) | 2605.06788 | audit / rollback | Not core. |
| 26 | ShieldAgent (Chen et al., 2025) | 2503.22738 | comparator | Not an authority floor. |
| 27 | GuardAgent (Xiang et al., 2024) | 2406.09187 | matrix `positioning_only` | Comparator only. |
| 28 | A Benchmark for Evaluating Outcome-Driven Constraint Violations, ODCV (Li et al., 2025) | 2512.20798 | RF-10 policy gaming | P1 eval: KPI pressure against constraints. |
| 29 | SHADE-Arena (Kutasov et al., 2025) | 2506.15740 | roadmap §11 excluded as first-class (API keys) | Run after BashArena, outside the deterministic test contract. |
| 30 | InjecAgent (Zhan et al., 2024) | 2403.02691 | matrix `positioning_only` | External injection eval. |
| 31 | Agent-SafetyBench (Zhang et al., 2024) | 2412.14470 | none | Breadth eval. |
| 32 | R-Judge (Yuan et al., 2024) | 2401.10019 | matrix `positioning_only` | Oracle comparator. |
| 33 | ToolEmu (Ruan et al., 2023) | 2309.15817 | matrix `positioning_only`; shadow mode | Replay comparator. |
| 34 | Games for AI Control (Griffin et al., 2024) | 2409.07985 | threshold theory | P2. |
| 35 | A Gentle Introduction to Conformal Prediction (Angelopoulos & Bates, 2021) | 2107.07511 | matrix `positioning_only` | Foundation. |
| 36 | Conformal Language Modeling (Quach et al., 2023) | 2306.10193 | none | Low direct relevance. |
| 37 | Semantic Uncertainty (Kuhn et al., 2023) | 2302.09664 | RES-002 bibliography; `remora/semantic_entropy.py`; NR §3 | Grounds implementation; parity unmeasured (RF-06). |
| 38 | Self-Consistency (Wang et al., 2022) | 2203.11171 | RES-004a `implemented_line` | Implemented. |
| 39 | Judging LLM-as-a-Judge (Zheng et al., 2023) | 2306.05685 | RES-004b `implemented_line` | Implemented; bias catalogue. |
| 40 | ImpossibleBench (Zhong et al., 2025) | 2510.20270 | nearest-unblocked / eval gaming | P1 eval with ODCV. |
| 41 | Agentic Misalignment (Lynch et al., 2025) | 2510.05179 | threat model | Not a feature. |
| 42 | Narrow Secret Loyalty Dodges Black-Box Audits (Lamerton & Roger, 2026) | 2605.06846 | oracle diversity, red team | Context. |
| 43 | The Obfuscation Atlas (Taufeeque et al., 2026) | 2602.15515 | white-box monitor threat | Context. |
| 44 | Neural Chameleons (McGuinness et al., 2025) | 2512.11949 | white-box threat | Context. |

## Tier C (threat model; do not build detectors from these)

| # | Work | arXiv | Lesson already taken |
|---|---|---|---|
| 45 | Chain of Thought Monitorability (Korbak et al., 2025) | 2507.11473 | CoT never grants authority |
| 46 | Monitoring Reasoning Models for Misbehavior (Baker et al., 2025) | 2503.11926 | monitor pressure produces hidden intent |
| 47 | Opaque Serial Depth (Brown-Cohen, Lindner, Shah, 2026) | 2603.09786 | reasoning without visible CoT |
| 48 | Full-bandwidth transformer (Wang et al., 2026) | 2608.08888 | latent recurrence |
| 49 | Sleeper Agents (Hubinger et al., 2024) | 2401.05566 | triggered backdoors persist |
| 50 | Alignment Faking (Greenblatt et al., 2024) | 2412.14093 | selective compliance |
| 51 | In-context Scheming (Meinke et al., 2024) | 2412.04984 | oversight subversion |
| 52 | Scheming AIs (Carlsmith, 2023) | 2311.08379 | theory |
| 53 | Situational Awareness Dataset (Laine et al., 2024) | 2407.04694 | eval-awareness candidate |
| 54 | AI Sandbagging (van der Weij et al., 2024) | 2406.07358 | eval validity |
| 55 | Measuring Reward-Seeking via Contrastive Belief Updates (Højmark et al., 2026) | 2607.18966 | reward-channel threat |
| 56 | AI Agents Enable Adaptive Computer Worms (Guan et al., 2026) | 2606.03811 | adaptive attacker |
| 57 | Haiku to Opus in Just 10 bits (Rinberg et al., 2026) | 2604.02343 | bit-budget idea, no implementation |
| 58 | Corrigibility Transformation (Hudson, 2025) | 2510.15395 | theory, outside runtime |
| 59 | Modular Pretraining Enables Access Control, GRAM (Roland et al., 2026) | 2607.08077 | model-side complement |

## Casper, The Engineer's Interpretability Sequence (2023–2025): what transfers

Thesis for a governance gate: a safety tool is as good as its margin over
trivial baselines on tasks it did not choose. Transferable items, with the
sources resolved:

| Idea | Source | Where it would land |
|---|---|---|
| Planted violations with known ground truth ("trojan recall") per stage | Casper et al. 2302.10894; Denain & Steinhardt 2206.13498 | new experiment under `experiments/`, pre-registered |
| Blind auditing game over the DecisionEnvelope trail | Marks et al. 2503.10965 | tests whether audit supports investigation |
| Report every release against regex blocklist, single LLM judge, always-VERIFY, block-all | Casper IV/XIII/XIV | SAP; NR §57 shows why: block-all also reaches FAR=0 |
| Red-team the oracles themselves; measure vote flips and transfer | Ziegler et al. 2205.01663; Liu et al. 1611.02770 | oracle robustness experiment |
| Keep Stage 1 inherently interpretable, versioned rules | Rudin 1811.10154 | already the design; argue it, do not add judges |
| Black-box access is insufficient for rigorous audits | Casper et al. 2401.14446 | audit design, access levels |
| Benchmarks: BackdoorBench 2206.12654; SNAFUE 2211.10024; SD filter red team 2210.04610 | none | method templates only |

The RF-16..RF-22 requirement set derived from this sequence (baselines,
trojan recall, sealed outsider test set, oracle adversarial eval, drift
detector, fix-with-one-change, prediction scoring) is an external proposal.
It is not in `docs/13-research-frontier-roadmap.md`. If adopted, each needs a
roadmap section, a shelf or matrix row and a pre-registered target.

## Standards and reports

| Source | REMORA status | Gap |
|---|---|---|
| Crosby & Wallach 2009, tamper-evident logging (USENIX Security) | principle used in hash chain | add as PROV-01 prior art |
| RFC 6962 Certificate Transparency | Merkle primitives in `remora/audit/merkle.py` | external anchoring not wired (RF-08, REM-025) |
| RFC 3161, RFC 8785 | cited in code (`code_citations`) | none |
| NIST AI 600-1, NIST AI RMF 1.0 | internal mappings exist | no independent assessment |
| EU AI Act 2024/1689 Art. 9–15 | mapping exists | no conformity claim; mapping is not compliance |
| ISO/IEC 42001 | little verified mapping | only if commercially required |
| OWASP Top 10 for LLM / Agentic Top 10 | mapping + evidence corpus | refresh version terminology |
| GDM AI Control roadmap, UK AISI Loss of Oversight, METR tool-call spoofing incident | not integrated | threat checklist candidates; retrieve primary documents first |

## Suggested order of work (research integrity before new mechanisms)

P0 research integrity: PROV-01..17 prior-art review as `PA-REV` entries; bind AEGIS, CaMeL,
Progent, AgentSpec and classic audit/capability prior art; correct matrix
drift (CRC two levels, LTT, AgentDojo); one canonical candidate register.

P1 falsify REMORA: BashArena, MonitoringBench, FORTRESS, AgentAbstain /
Agentic Abstention, persistent-state attacks, ODCV + ImpossibleBench,
context-rot padded needle.

P1/P2 only if falsification shows the gap: CaMeL-class per-argument IFC,
AgentLTL semantics over RES-018, resample/max-suspicion on a VERIFY-bearing
dataset, role-confusion sensor as non-authoritative signal, Auditable Agents
card.

Not core: ShieldAgent/GuardAgent as authority floor, CoT monitoring,
sleeper-agent detection, activation-probe arms race, corrigibility
transformation, GRAM, reviving thermodynamic or Lyapunov claims (NR §18/§38).
