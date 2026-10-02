# REMORA Results Snapshot

Generated snapshot of `results/ablation_v2_results.json` (N=302, internal
ablation) by `scripts/generate_results_snapshot.py`.

This file is **not a governed claim source**. Governed claims, with their
evidence and caveats, live in `docs/assurance/claim_register_v1.yaml`; cite
those, not this snapshot.

## Benchmark

- Total items: 302
- TruthfulQA: 85
- BoolQ: 135
- Curated: 75
- Adversarial curated: 7

## Headline Metrics (N=302)

| Condition | Accuracy | ETR |
|---|---:|---:|
| A Single | 57.0 % | - |
| B Majority | 82.8 % | - |
| C REMORA full | 69.5 % | 12.9 % |
| D2 Router BALANCED | 82.1 % | 43.4 % |
| D3 Router HYBRID | 76.2 % | 40.7 % |

## Heuristic Readiness Score (not a claim)

An internal heuristic score over this one result file. It is not evidence of a
breakthrough and is not used by the claim register.

- Heuristic score: 87.0/100
- Accuracy gain vs single oracle: 25.2 pp
- D2 vs majority delta: -0.7 pp
- ETR gain vs full REMORA: 30.5 pp

## Gap Analysis

- Benchmark scale is still below a 500+ item external validation threshold.
- D2 is competitive with majority voting, but not yet separated strongly enough to claim a decisive accuracy breakthrough.
- Effective Truth Rate is materially improved, but still below a high-assurance 50%+ target on the external benchmark.
- The canonical v2 result set does not yet include a Cloudflare oracle swarm comparison.

## What Would Be Needed For A Stronger Claim

- Rebuild the benchmark with the LARGE or XL preset and rerun ablation_v2.
- Add cross-provider and Cloudflare-backed ablations to show a stronger margin over adjacent baselines.
- Increase evidence coverage in the Cloudflare corpus and benchmark the RAG oracle inside the main swarm on the full benchmark.
- Run a dedicated Cloudflare swarm benchmark using reranking, multilingual embeddings, 70B routing, and dual-consensus enabled.
