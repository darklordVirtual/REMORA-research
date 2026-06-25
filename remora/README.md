# REMORA Package Guide

This package is organized by capability rather than by a single monolithic core.
The main active surfaces are:

- `engine.py` for the multi-oracle consensus loop
- `policy/` for decision routing and invariants
- `governance/` for envelopes, audit chains, and nested governance helpers
- `evidence/` for evidence providers and evidence-backed routing
- `cascade/` for staged execution and critique/revision flows
- `toolcall/` for benchmark and simulator plumbing
- `shadow/` for replay and governance-delta analysis

Counterfactual logic is now canonical in `counterfactual.py`.
The legacy `causality.py` and `causality_v2.py` modules remain as thin
compatibility wrappers so existing imports continue to work while the codebase
uses one documented implementation.

Modules under `future_concept/`, `proofs/`, and parts of `toolcall/` are
intentionally experimental or benchmark-specific. Keep claims about those areas
scoped to the artifacts and tests that validate them.