# Evidence Sufficiency Conformance Review v1

**Status:** research/conformance artifact. Synthetic author-run only. Not a standard, certification, production control, APS result or CoSAI deliverable.

This additive suite formalizes a narrow question left deliberately separate from `decision-to-effect-v1`:

> Given an accepted observation set, what bounded property claim is the evidence actually sufficient to establish?

The existing `decision-to-effect-v1` suite remains unchanged. That suite has external provenance and has already been reproduced by another participant. This directory therefore does not rewrite, renumber or reinterpret any of its 15 vectors.

## Three layers that must not collapse

The runner records three different answers:

1. Runtime outcome: what the implementation/runtime reported, such as `EFFECT_INDETERMINATE`.
2. Case result: whether the synthetic checker matched the authored fixture expectation.
3. Evidence verdict: whether the accepted observations establish, violate or fail to establish one bounded property.

A case can correctly match an expected `not_established` result without establishing the underlying property.

## Claims modeled

- `admission_accounting`: whether accepted evidence establishes a covering admission for an observed execution. Missing admission evidence is decisive only under a justified closed observation scope.
- `tested_route_enforcement`: whether one named alternative route demonstrates or refutes enforcement. A direct observed effect outside the required PEP refutes the claim; a refusal earns positive credit only with an isolating valid control, complete downstream observation and accepted boundary attribution.
- `postcondition_observed`: whether an accepted, fresh, bound read-back agrees with the declared postcondition at the declared settlement point. This does not establish causation.

## Why `not_established` is first-class

Two hidden histories can produce identical verifier inputs. For example, an execution with no matching admission in an incomplete export is consistent both with a real bypass and with a legitimate admission omitted from the export. A sound checker cannot distinguish those worlds from identical observations, so it must remain `not_established` until distinguishing evidence is supplied.

Every inconclusive verdict carries `missing_evidence` and `decisive_if` fields so the artifact states what additional evidence would make the claim decidable.

## Synthetic premise boundary

The checker accepts only `premise_source="synthetic_fixture"`. Fields such as `*_accepted`, completeness flags and timing flags are trusted fixture premises. Production adapters MUST NOT expose these as caller-controlled booleans and treat them as proof. A production implementation would need independent provenance validation, scope construction, coverage/finalization evidence and trust policy before comparable inference rules could be applied.

## Run

```bash
python conformance/evidence-sufficiency-v1/run_evidence_sufficiency.py \
  --out /tmp/evidence-sufficiency-run.json

python conformance/evidence-sufficiency-v1/run_evidence_sufficiency.py --check
```

The committed `run-record.json` is deterministic and `--check` reproduces it byte-for-byte. It contains no timestamp or environment-dependent value.

## What the regression checks establish

The suite checks authored fixture expectations, two indistinguishable-world witnesses, bounded single-field evidence erasure, rejection of five deliberately wrong shortcuts, and the rule that empty evidence never creates a decisive claim. These are regression checks for the proposed inference rules. They are not independent validation.

## Non-claims

Passing this suite does not establish production non-bypassability, complete logging, source trust, policy correctness, causal effect attribution, external implementation conformance, APS conformance or CoSAI acceptance.
