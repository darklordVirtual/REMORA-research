# How do I contribute a result, fix, or new oracle?

## Adding a result

1. Run the experiment using the commands in `06-reproducibility.md`.
2. Commit the result artifact to `results/` or `artifacts/`.
3. Update `docs/02-evidence-and-claims.md` with the claim, artifact pointer, and caveat.
4. If the result is negative or a limitation, add it to `NEGATIVE_RESULTS.md`.
5. Never add a number to README, the paper, or any claim document without the artifact.

## Claim hygiene rule

See `docs/05-claim-hygiene.md`. No claim without an artifact. No artifact without a reproduce command.

Every claim must include:
- the N (sample size),
- the confidence interval (Wilson 95% CI for proportions),
- the caveat on scope (simulator-scoped, holdout-scoped, benchmark-scoped),
- and a pointer to the exact artifact file.

## Adding an oracle or backend

1. Implement the oracle in `remora/` following existing patterns in `remora/oracles/`.
2. Add a test in `tests/` with at least one negative case.
3. Run `make test` and confirm all tests pass.
4. Update `docs/07-api-reference.md` with the new interface.
5. Add any new public API surface to the `Oracle` ABC, see `remora/core.py`.

## Negative results

Negative results are first-class. If you run an experiment and it does not replicate or shows a limitation:

1. Do not discard the artifact.
2. Add an entry to `NEGATIVE_RESULTS.md` with the finding, what was tried, and what remains open.
3. Update the relevant caveat in `02-evidence-and-claims.md`.

See `04-negative-results-detail.md` for examples of how active findings are documented.

## Language rules

Use these phrases:
- "policy-modelled counterfactual"
- "actionable policy requirement"
- "bounded by documented assumptions"

Never use:
- "formal guarantee"
- "proven safe"
- "real-world causal proof"
- "causally safe"

## External review

Open an issue with the "external-review" template (`docs/external-review.md`). Provide:
- the claim being tested,
- the exact reproduce command,
- the artifact you compared against,
- your result (even if it matches: positive replications are also valuable).

Negative findings are explicitly welcome and will not be suppressed.

## Pull request checklist

- [ ] `make test` passes
- [ ] `python scripts/check_claim_consistency.py` passes
- [ ] Any new claim has an artifact pointer in `02-evidence-and-claims.md`
- [ ] Any failure or limitation is in `NEGATIVE_RESULTS.md`
- [ ] No secrets in committed files (see CLAUDE.md)
