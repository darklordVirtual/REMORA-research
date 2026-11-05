# OT pilot execution path, reproduced on the head of PR #1171 (2026-11-05)

PR #1171 adds tests and changes no enforcement code. This folder shows that the deployed pilot behaves as recorded, on the build the PR would merge. The pilot was built from commit `cbb8cadc` in production mode, with the signed ToolSpec, WS1 in shadow and the signed cumulative limits. Commit `456648b0` changes only `tests/` and `provenance/` relative to it, so the runtime is byte-identical. `manifest.json` holds the image id, the policy hash and the SHA-256 of every deployment file and runner.

| Run | Stack | Result | Compared with |
|---|---|---|---|
| `battery/` (`run_ot_battery.py`) | freshly built | 16 of 16 cases as specified; 5 of 5 monitoring reads completed with no review; execution chain valid | `grounded-reads-2026-11-03/battery-toolspec-ws1/`: the same decision, outcome and refusal reason in all 16 cases |
| `fault-injection/` (`run_fault_injection.py`) | after `down -v` | 10 of 10 faults as specified; 8 of 8 intended writes completed, 0 false refusals, 14 human steps | `grounded-reads-2026-11-03/fault-injection-toolspec-ws1/`: 10 of 10 |
| `independent-scenarios/` (`run_independent_scenarios.py`, phases a, b, c) | each phase after `down -v` | 20 of 24 pass; S06 and S09 executed their tool after the scripted approver approved; S17 and S22 were routed to a human where refusal was demanded | `grounded-reads-2026-11-03/independent-scenarios/`: the same verdict in all 24 scenarios |

The three refusals in the battery come from three different controls. The unknown tool is refused by the ToolSpec (`toolspec_unknown_tool`). The loop that does not exist is refused by the limits observer (`limit_observation_unavailable`). The move past the hourly cap is refused by the cumulative limit (`limit_exceeded`). The tampered argument is refused at binding before the approved call runs. Replays get HTTP 409. The operator's attempt to approve gets 403.

## What this does not show

- The four scenario failures are the negative result recorded on 2026-11-04, reproduced here and not resolved. H2 of `docs/assurance/ws1_utility_test_plan_v1.md` (no should-block scenario executes a tool) is still not met. The engine routes a target mismatch (S06) and a goal mismatch (S09) to a human, and a human who approves without reading lets them through. WS1 is in shadow, so its `abstain` for S06, S17 and S22 changed nothing.
- The plant is simulated in the API process. One host, one replica, the SQLite limit ledger.
- There is no holdout of legitimate writes, so the rate at which `limit_exceeded` refuses a write an operator would have made is not measured (NEGATIVE_RESULTS §97).
- The battery manifest records `commit_sha: local` because the runner does not read Git. The commit is the one named above and in `manifest.json`.

## Reproduce

```
git checkout 456648b0
python deploy/ot-pilot/init_tokens.py
python deploy/ot-pilot/build_toolspec.py
set -a; . deploy/ot-pilot/.env; set +a
docker compose -f deploy/ot-pilot/docker-compose.yml up --build -d --wait
python deploy/ot-pilot/run_ot_battery.py --evidence-root /tmp/ev/battery
docker compose -f deploy/ot-pilot/docker-compose.yml down -v
docker compose -f deploy/ot-pilot/docker-compose.yml up -d --wait
python deploy/ot-pilot/run_fault_injection.py --evidence-root /tmp/ev/faults
# one phase per fresh stack (down -v, then up -d --wait, before each):
S=artifacts/ot-pilot/grounded-reads-2026-11-03/independent-scenarios/scenarios_v1.json
python deploy/ot-pilot/run_independent_scenarios.py --scenarios $S --out /tmp/ev/phase-a \
  --only S01,S02,S03,S04,S05,S06,S07,S08,S09,S10,S11,S12,S13,S14,S15,S16,S17,S18,S19,S21,S22,S23
python deploy/ot-pilot/run_independent_scenarios.py --scenarios $S --out /tmp/ev/phase-b --only S20
python deploy/ot-pilot/run_independent_scenarios.py --scenarios $S --out /tmp/ev/phase-c --only S24
```

Copyright 2026 Stian Skogbrott. Licensed under BUSL-1.1 (`legal/LICENSING.md`); rights ownership in `legal/COPYRIGHT.md`.
