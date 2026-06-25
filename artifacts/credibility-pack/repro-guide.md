# REMORA Credibility Pack Reproduction Guide

This document accompanies the credibility pack and provides reproducibility commands and limitations references.

## Reproduction commands

```bash
# 1) Environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2) Core verification
pytest -q

# 3) Heavy replay segment
pytest -q -m live_replay_heavy \
  tests/test_toolcall_live_exec_results.py \
  tests/test_toolcall_live_cache_replay.py

# 4) Benchmark + holdout
make benchmark
make holdout

# 5) Governance benchmark package
make benchmark-package

# 6) Claim and consistency checks
python scripts/check_claim_consistency.py
python scripts/check_no_overclaims.py
python scripts/check_claim_sync.py
```

## Limitations and scope

- Read [NEGATIVE_RESULTS.md](../NEGATIVE_RESULTS.md) first.
- Tool-call safety figures are benchmark/simulator scoped, not production guarantees.
- Evidence verification pathways include proxy and retrieval-backed modes; external semantic validation remains an active workstream.
- REMORA is evaluated as a governance overlay around agent actions, not as an agent replacement.
