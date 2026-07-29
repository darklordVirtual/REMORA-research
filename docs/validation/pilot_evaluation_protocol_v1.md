# Pilot evaluation protocol v1 (PROPOSED)

**Status:** PROPOSED — a pre-registered evaluation framework for REMORA's
first external shadow-mode pilot. Not yet agreed with a pilot partner; the
example targets below are starting points to be calibrated per domain
*before* the pilot starts, never after the data is in.

**Source:** external review 2026-07-29 (independent reviewer), adopted here
so the pilot design is versioned and reviewable like everything else.
Companion documents: [external-review.md](external-review.md) (how to review
the research), [release_gates.md](../assurance/release_gates.md) (what gates
a profile promotion), REM-021/REM-023 in the
[remediation register](../assurance/remediation_register.yaml) (what still
blocks `CONTROLLED_PILOT`).

---

## Preconditions — what a credible pilot requires

A pilot is credible only with all of these in place. They are constraints on
*us*, not on the partner:

1. **Developer support** — the pilot is assisted, not self-served.
2. **Locked deployment** — a tagged repo checkout or verified container,
   not an ad-hoc wheel install (containerised reference deployment is
   tracked in issue #89).
3. **Bounded scope** — a named set of tools/workflows; nothing else.
4. **Explicit context** — risk/action metadata from the partner's tool
   registry; name inference (`infer=True`) is bootstrap/analysis aid only
   and never drives verdicts that count.
5. **Human ground truth** — expert labels for the decisions being scored,
   with inter-rater agreement measured.
6. **This protocol agreed in advance** — metrics, thresholds and stop
   conditions frozen before the first scored event.
7. **Observer-only by default** — shadow mode; no live enforcement. Any
   step beyond that follows the release-profile ladder, not pilot
   enthusiasm.

Out of scope for any pilot at the current maturity: inline OT/BMS control.
That requires deterministic fail-safe state, independent interlocks, an
explicit authority boundary, safe-state recovery, change control and a
separate hazard analysis — none of which this repository claims to provide.

---

## Measurement criteria

### Decision quality
- Precision for blocking and escalation
- Recall for known risk events
- False-positive rate; false-negative rate
- Agreement with human expert judgement
- Inter-rater agreement between reviewers (report alongside, so "agreement
  with the expert" is interpretable)

### Selectivity and workload
- Share allowed / blocked / routed to review
- Review time per event; events per reviewer
- Share of events where the *explanation* changed the human decision

### Stability
- Variation across models, prompt versions, and policy versions
- Sensitivity to missing or ambiguous context
- Stability under repeated runs (determinism where determinism is expected)

### Technical performance
- p50 / p95 / p99 latency; error rate; throughput; resource use

---

## Go / no-go framework (example targets — calibrate per domain)

| Criterion | Example target |
|---|---|
| Technical completion | ≥ 99% of relevant events assessed |
| Missing audit data | < 1% |
| Replay stability | ≥ 99% deterministic agreement where determinism is expected |
| Human-review agreement | Documented and measured per risk class |
| False-positive rate | Within the domain's pre-agreed tolerance |
| Critical false negatives | None without documented analysis and remediation |
| Review workload | Low enough that the pilot process is operationally realistic |
| Explainability | Majority of reviewers rate the explanations understandable |

**A pilot is not successful because the system ran.** Success means REMORA
demonstrably produced a better decision basis, surfaced relevant deviations,
or reduced uncertainty at an acceptable cost — measured against the criteria
above, decided against thresholds fixed in advance.

---

## Stop conditions

Define before start; suggested defaults:

- Any critical false negative without immediate root-cause analysis → pause
  scoring until analysed.
- Audit-data loss above the threshold → pause; fix pipeline before resuming.
- Reviewer workload rendering the process unrealistic → renegotiate scope,
  do not silently drop events.

---

## Reporting

Every scored event keeps its `DecisionEnvelope`; the pilot report cites the
protocol version, the frozen thresholds, the measured values with
denominators, and every stop-condition trigger. Negative findings are
reported with the same prominence as positive ones — the same rule the rest
of this repository follows.
