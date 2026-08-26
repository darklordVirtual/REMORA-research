# Claim Evidence Matrix

> **Status: pointer, not authority.** The machine-checked claim-to-evidence
> binding lives in `docs/assurance/claim_register_v1.yaml` (sole authority) and
> is enforced by `scripts/check_claim_provenance.py` and
> `scripts/check_claim_sync.py` in CI. This page exists so the documentation
> navigation has a human-readable entry point; it carries no claims of its own.

To trace a claim:

1. Find its `CLAIM-nnn` id in `docs/assurance/claim_register_v1.yaml`.
2. The entry lists status, evidence artifacts (paths under `artifacts/`,
   `data/`, `tests/`) and the scope boundary.
3. `python scripts/check_claim_provenance.py` verifies every listed artifact
   exists and every README/paper anchor resolves to a register entry.

Status vocabulary is defined in the register, not here. Do not add rows to
this file; add or amend register entries so the CI gates see them.
