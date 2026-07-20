# AROMER Memory-Governance Policy v1

**Status:** POLICY SPECIFICATION. Some stages are enforced in code today; the
write-anomaly, quarantine, deletion/retention, and mutation-audit stages are
roadmap. This document states the policy and marks honestly what is enforced vs.
what is a gap.
**Created:** 2026-07-20
**Scope:** AROMER's persistent learning state only. AROMER is experimental
(`internal_simulation`), `SHADOW_ONLY`, and its Autonomous Intelligence Index is
**not** a safety metric — do not cite AROMER numbers as evidence for the core
governance engine (see [assurance_case_v1.md](assurance_case_v1.md) §8).
**Legal note:** the GDPR/retention/erasure references below are for design
orientation only; not legal advice.

The compendium treats long-term agent memory as a **governance object with its
own lifecycle**, not an internal implementation detail: because it is
persistent, shared, and self-modifying state, it is simultaneously a poisoning
target, an exfiltration channel, and a persistence mechanism for an attacker.
The lifecycle stages — **write, store, retrieve, execute, share, delete** — must
each be governed, and the memory must be inventoried as an attack surface with
an explicit **write / quarantine / delete** regime. This document applies that
frame to AROMER.

---

## 1. Memory inventory (attack surface)

| Store | What it holds | Persistence | Path |
|---|---|---|---|
| World-model priors | Bayesian `(action_type × risk_tier × domain)` harm priors (Beta α/β) | `~/.aromer/world_model.json`; D1 `world_model_priors` | `remora/aromer/world_model/domain_prior.py`, `workers/aromer/src/index.ts`, `workers/aromer/src/schema.sql` |
| Episodic store | Append-only decision episodes with outcomes/labels | `~/.aromer/episodes.jsonl`; D1 `episodes` | `remora/aromer/experience/store.py`, `remora/aromer/experience/episode.py` |
| Shadow log | In-memory diagnostic trace of trust adjustments | none (RAM only) | `remora/aromer/world_model/domain_prior.py` |

## 2. Per-stage policy and current enforcement

### Write

**Policy.** Every write must carry provenance and a trust weight; self/heuristic
labels must never enter at the strength of observed ground truth; anomalous or
adversarial writes must be gated.

**Enforced today.** Episodes *record* provenance fields — `label_source`
(human/synthetic/oracle/auto_label/replay_truth/unknown), `label_confidence`,
`synthetic`, `can_train`, `oracles_used` (`remora/aromer/experience/episode.py`).
Two down-weighting mechanisms exist: the TTL-presumed-benign path applies a weak
0.25 weight, and a negative MetaJudge critique floors a label's influence at 0.1
(`workers/aromer/src/index.ts`).

**Gap.** There is **no anomaly gate on ingestion, and no provenance-based
down-weighting.** The world-model update weight
(`DecisionQuality.world_model_weight` in `remora/aromer/experience/episode.py`;
`worldUpdate()` in `workers/aromer/src/index.ts`) is a pure function of
*decision quality* (verdict × ground-truth outcome) and never reads
`label_source`, `label_confidence`, or `synthetic` — so it separates clear vs.
review outcomes, **not** trusted vs. self-labeled provenance. Consequently the
auto-label hook (`scripts/aromer_auto_label_hook.py`), which self-labels
essentially every dev-session tool call `correct_accept` with no external
verification, updates the world model at the **full 1.0 weight** — the same
strength as observed ground truth. The 0.25 weak weight applies only to review
outcomes and the TTL-presumed path, never to this self-labeling path. The
distinction is not schema-enforced in D1 either (those provenance fields live in
a `meta` JSON blob, not typed columns). This is the poisoning surface; a real
quarantine plus provenance-gated weighting is the core of REM-043. The **Policy**
above (self/heuristic labels must not enter at ground-truth strength) is
therefore a target, **not** an enforced control today.

### Store

**Policy.** Confidence must saturate at a finite ceiling (regime change stays
learnable); on-disk state must be bounded or retention-governed.

**Enforced today.** Prior evidence mass is capped and rescaled at
`_MAX_EVIDENCE = 200` in Python (`domain_prior.py`) and mirrored by
`capPriorMass()` / `WM_MAX_EVIDENCE = 200` in the worker
(`workers/aromer/src/index.ts`). The diagnostic shadow log is a
`deque(maxlen=1000)`. The episodic store bounds the **in-RAM** working set at
`max_loaded = 10_000` (`remora/aromer/experience/store.py`).

**Gap.** The on-disk episode JSONL is **append-only and unbounded**; `max_loaded`
bounds memory/retrieval, not the file.

### Retrieve

**Policy.** Retrieval must be bounded and must not resurface quarantined records.

**Enforced today.** Retrieval is bounded by `max_loaded`.
**Gap.** No quarantine state exists to exclude from retrieval (see below).

### Execute / adapt

**Policy.** Adaptation must not be driven by unverified or poisoned records; a
holdout must gate any relaxation.

**Enforced today.** `load_holdout()` selects `can_train == False` episodes as a
holdout that must keep `false_accept_rate == 0` before friction is relaxed
(`remora/aromer/learning/friction_optimizer.py`,
`remora/aromer/evals/external_holdout.py`). A two-stage TTL relabels stale
pending ACCEPTs as presumed-benign at the weak 0.25 weight (never 1.0) and flags
7-day-stale non-ACCEPTs as expired without inventing a label
(`remora/aromer/experience/store.py`, `workers/aromer/src/index.ts`).

**Gap.** The holdout's purpose is train/eval separation, **not** quarantine of
poisoned data.

### Delete

**Policy.** There must be a configurable retention window and a deletion path
(including GDPR-style erasure for any personal data that reaches memory).

**Gap (whole stage missing).** No deletion exists anywhere in AROMER memory. The
JSONL store has no prune/purge path; the D1 `episodes` table has no TTL deletion
or retention cron; the TTL "resolution" only **relabels/flags**, never removes.
There is no retention window for episodes or priors.

### Share

**Policy.** Personal data flowing through context, memory, tool calls, and logs
must be mapped, since each is its own processing site with its own leakage path.

**Gap.** No data-flow map of personal data through AROMER memory exists; this is
part of the broader DPIA gap (REM-031).

## 3. Quarantine regime (required; currently missing)

The compendium requires an explicit quarantine capability. AROMER has **none**:
no per-episode `quarantined`/`suspect` state, no anomaly gate, and nothing reads
a `corpus_excluded` flag.

> **Provenance note (honesty).** `corpus_excluded` is referenced in
> [remediation_register.yaml](remediation_register.yaml) (REM-019) as a D1 `meta`
> filter, but the string appears in **no** worker code, Python module, schema, or
> test in this repository, and its referenced implementing script/test are not
> present here (the regression artifact was produced in the separate main
> implementation repo and copied in). In *this* repo, `corpus_excluded` is
> documentation, not a verifiable control.

## 4. Mutation audit (required; currently missing)

There is no before/after audit of memory changes. World-model priors are
overwritten wholesale by `_save()`; episode mutations rewrite the JSONL in place;
the D1 `adaptation_cycles` table records only cycle-level aggregates. The shadow
log is in-memory, diagnostic, and unpersisted. A memory change is a change of the
system (a change-gate surface); it must be audited like one.

## 5. Roadmap to close (tracked in REM-043)

| Requirement | Current | Target |
|---|---|---|
| Ingestion anomaly gate + typed provenance columns | weight convention + `meta` blob | schema-enforced `label_source`/weight; reject/hold anomalous writes |
| Quarantine state | none | per-episode `quarantined` flag honoured on retrieve and adapt; wire the documented `corpus_excluded` filter into real code + tests |
| Retention / deletion | none | configurable retention window; deletion path incl. erasure |
| Mutation audit | none | append-only before/after log of prior and episode mutations, hash-chained like the decision audit |
| Data-flow map | none | map personal-data flow through memory (feeds DPIA, REM-031) |

## 6. Standing constraints

- AROMER remains `SHADOW_ONLY`; its Autonomous Intelligence Index is an adaptive
  composite, not a safety metric.
- Episode labels are partly self-labeled: `scripts/aromer_auto_label_hook.py`
  labels essentially every dev-session tool call benign, so a benign bias is
  possible (the hook itself is the direct evidence). Related disclosed negative
  results on AROMER's metadata dependence and holdout non-transfer are in
  [NEGATIVE_RESULTS.md](../../NEGATIVE_RESULTS.md) §2 and §8.
- Until the quarantine and mutation-audit stages exist, AROMER's learning must
  not be relied on for any safety-relevant decision; the deterministic policy
  floor — not AROMER — carries the safety result.
