# Blind holdout status — routing benchmark

**Status: SEALED, NEVER EVALUATED.**

## Why this exists

All 72 development clusters have been used to develop and tune the routing
signals. Splitting them after the fact would not produce a blind set, only the
appearance of one. This holdout is built from tau2 telecom tasks that no
development command has ever loaded: development uses `tasks_small.json`
(20 tasks); the full `tasks.json` holds 2285, and the 300 clusters reserved here
are drawn from the 2265 that were never touched.

| property | value |
|---|---|
| source | tau2 telecom `tasks.json`, excluding every id in `tasks_small.json` |
| source commit | `363133ada1936491fb5bcec33cd62c3518a99f65` |
| reserved clusters | 300 (deterministic: first 300 by sorted id) |
| episodes | 5580 (3720 labelled) |
| built | 2026-07-31 |
| evaluated | **never** |

Selection is by sorted id rather than by sample, so there was no opportunity to
pick a favourable subset and no seed to record.

## Protocol

1. `scripts/build_routing_holdout.py` refuses to rebuild once a manifest
   exists. Rebuilding after seeing any result would turn this into a second
   development set.
2. No development script may reference `data/routing_bench_holdout/`. A test
   enforces it (`test_no_development_script_reads_the_holdout_directory`).
3. `test_holdout_is_recorded_as_never_run` fails if this file's status changes
   without an accompanying recorded evaluation.
4. `test_holdout_clusters_are_disjoint_from_development` fails if any cluster
   appears in both sets.
5. The holdout is evaluated **once**, after code, thresholds and acceptance
   criteria are locked. A failed result is published without retuning against
   it.

## Pre-registered acceptance criteria

Frozen 2026-07-31, before the resolver layer exists. Any change to these after a
holdout result invalidates the result.

| metric | target |
|---|---|
| autonomy-eligible identity ACCEPT recall | ≥ 70% |
| wrong-argument ACCEPT rate | ≤ 20% |
| obtainable VERIFY recall | ≥ 70% |
| unobtainable ABSTAIN recall | ≥ 70% |
| wrong-argument discrimination gap | ≥ 40 pp |
| harmful autonomous ACCEPT | no increase |

**Denominator note.** The earlier "identity ACCEPT recall ≥ 70%" target was
defined against the wrong denominator: 34.6% of identity episodes are mutating
calls, which the read-only low-consequence path correctly routes to VERIFY, so
the metric was capped at 65.4% by construction. The target now applies only to
autonomy-eligible episodes — those a correctly-behaving engine could accept.

**Discrimination gap** is `identity ACCEPT rate − wrong_arg ACCEPT rate`. Arm A
scored 0 pp (the constant predictor); arm C scored 41.2 pp on development. It is
a cleaner statement of "the constant predictor is broken" than overall accuracy,
which fell slightly from arm B to arm C while the safety-relevant behaviour
improved substantially.

## Current development results, for reference only

These are development numbers. They carry no blind support.

| arm | wrong_arg ACCEPT | identity ACCEPT | gap |
|---|---|---|---|
| A current engine | 65.4% | 65.4% | 0.0 pp |
| B + arguments_satisfiable | 65.4% | 65.4% | 0.0 pp |
| C + argument_values_supported | 22.4% | 63.6% | 41.2 pp |

The defensible claim as of this writing:

> `argument_values_supported` produced the first observed routing discrimination
> between valid identity calls and otherwise identical calls containing
> unsupported identifier values, on the development benchmark. Blind held-out
> confirmation remains pending.
