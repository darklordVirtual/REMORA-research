# Runtime Policy

The thermodynamic controller is currently a router-gate policy layer, not a full-loop physics engine.

Current runtime rules:

- `enable_thermodynamic_control` only has effect when `enable_routing=True`.
- Thermodynamic control runs inside `Remora._router_gate()`.
- Only `action == "trust"` is allowed to take the fast path.
- `critical` and `disordered` states block the parametric fast path.
- If the phase controller requires evidence, the engine sets:
  - `require_rag = True`
  - `refuse_parametric_verdict = True`
- The engine then stops the parametric answer path for that subquestion.

Important boundary:

- The current core engine enforces an evidence-required guardrail.
- It does **not** by itself execute a complete external-evidence workflow unless a downstream RAG/evidence system is explicitly connected.
- The dedicated policy evaluator for this boundary is [experiments/thermodynamic_router_eval.py](../../experiments/thermodynamic_router_eval.py). That experiment is the place to test whether the guardrail improves selective accuracy or helps an external-evidence backfill policy.

So the precise current claim is:

> REMORA can block unsafe parametric fast-path acceptance and mark the item as evidence-required.

Not yet:

> REMORA has already demonstrated a full evidence-backed controller that beats simpler baselines end to end.

Update: the benchmark-scale evidence-backed controller has now been run on N500 and does beat plain majority, but only modestly and with very high evidence dependence.

Current evidence now exists in two layers:

- the canonical N302 artifact in [results/thermodynamic_router_eval_results.json](../../results/thermodynamic_router_eval_results.json), which is strongly negative and over-conservative,
- the calibrated N500 selective artifact in [results/thermodynamic_router_eval_n500_final_results.json](../../results/thermodynamic_router_eval_n500_final_results.json), which answers 18.2% of items at 86.9% answered accuracy while intercepting 95.9% of majority errors,
- and the calibrated N500 evidence-backed artifact in [results/thermodynamic_router_eval_n500_evidence_results.json](../../results/thermodynamic_router_eval_n500_evidence_results.json), which closes the full benchmark at 46.32% accuracy with 445 evidence calls.

That is a real runtime guardrail result. It still does **not** prove an end-to-end routing win because:

- 81.8% of items are still sent to evidence,
- the delta versus majority on the same answered slice is currently `0.0`,
- and the full evidence-backed controller, while now positive against majority at full coverage, is still too dependent on external evidence and too weak in absolute accuracy to count as a strong deployment result.
