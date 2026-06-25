# CLAUDE.md - working agreement for the REMORA repository

REMORA is a research-grade governance overlay for autonomous AI actions. It
decides whether an agent action is accepted, verified, abstained, or escalated
based on uncertainty, evidence, policy, auditability, and human review.

## Core rule

Claims must match code, tests, artifacts, and documentation. If a claim is not
supported by an artifact, downgrade it to roadmap or mark it as requiring
external validation. Never present REMORA as production-certified or
safety-guaranteeing.

## Non-negotiables

- No invented results. Do not write numbers into README, paper, badges, or
  abstracts unless the exact result artifact exists on disk.
- No claims without artifacts. See `docs/claim_hygiene.md` for the decision rule.
- Do not tune on test data.
- Do not silently skip failures. Surface them with non-zero exits or explicit
  `status:invalid` / `status:skipped` artifacts.
- Do not fake tool-call interception. The AgentHarm harness is intent-gating
  until `inspect_tools_probe.py` proves otherwise; see
  `experiments/agentharm/INTERCEPTION_NOTES.md`.
- Mask all secrets. Never print or write values of `CF_AIG_TOKEN`,
  `CF_AI_GATEWAY_KEY`, `CLOUDFLARE_API_TOKEN`, `OPENAI_API_KEY`, `HF_TOKEN`, or
  `GROQ_API_KEY`.

## Canonical contracts

1. `DecisionEnvelope` is the canonical governance contract. Keep it stable.
2. Shadow Mode / Replay Engine is REMORA's proof mechanism.
3. Mode degradation from full REMORA to hard-blocks-only must always be recorded.

## AgentHarm external validation

See `experiments/agentharm/README.md`. Run order:

1. Preflight.
2. Cloudflare and Hugging Face checks.
3. Tool exposure probe.
4. Baseline pilot.
5. Full matrix.
6. Scoring.

Scoring fails hard on missing baseline.

## Before code changes

Produce a brief diagnosis, files affected, proposed fix, tests to add, risk of
overclaiming, and acceptance criteria. Prefer small reviewable diffs over broad
rewrites. Add or update tests for any behavioral change. Do not remove negative
results or caveats.
