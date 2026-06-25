# REMORA v4 Thermodynamics

This section documents the current v4 thermodynamic layer as it exists in code.

It is important not to conflate two different things:

- the thermodynamic interpretation, which is a research program,
- the trust-routing behavior, which is the deployment-facing control insight.

The first is not yet a completed theory. The second is already useful, but only in its currently supported form: accept / verify / abstain / escalate decisions, not a fully solved autonomous routing policy.

REMORA v4 does three distinct things:

1. maps a pre-sweep oracle snapshot onto thermodynamic-style observables,
2. classifies that snapshot as `ordered`, `critical`, or `disordered`,
3. uses the resulting phase decision to control the router fast path.

What is implemented now:

- Helmholtz-style proxy `F(T) = λD - T·H` in [remora/thermodynamics.py](../../remora/thermodynamics.py)
- algebraic bridge `V(H,D) = F(T=-1;H,D)` for the historical Lyapunov potential
- order parameter `η`, susceptibility proxy `χ`, critical-temperature proxy `T_c`
- phase controller with actions `trust`, `iterate_cautious`, `refuse`, `demand_evidence`
- engine guardrail that blocks the parametric fast path when evidence is required
- benchmark policy evaluator in [experiments/thermodynamic_router_eval.py](../../experiments/thermodynamic_router_eval.py) for measuring guardrail coverage, selective accuracy, and error interception
- empirical N=302 artifacts, calibrated N500 artifacts, plus a live `χ` perturbation pilot

What is operationally useful now:

- the thermodynamic readout can be used as a trust-routing signal,
- the best-supported deployment result is now a calibrated N500 guardrail slice with non-zero coverage,
- the current hard guardrail is implemented and selective, and the evidence-backed N500 benchmark run is now completed, but the resulting full policy is still weak in absolute accuracy.

What is not implemented as a closed theory:

- formal Potts derivation
- universal critical exponents
- hallucination-bound proxy (not a proven formal upper bound; implemented as research heuristic)
- FDT-grade `χ` estimator
- partition function, heat capacity, correlation length, Maxwell construction, RG scaling

Canonical references:

- Evidence status: [docs/use-cases/REMORA_v4_Thermodynamics_Evidence_Status.md](../use-cases/REMORA_v4_Thermodynamics_Evidence_Status.md)
- Runtime policy: [docs/thermodynamics/runtime_policy.md](runtime_policy.md)
- Temperature estimator: [docs/thermodynamics/temperature_estimator.md](temperature_estimator.md)
- Limitations: [docs/thermodynamics/limitations.md](limitations.md)
- Claim ledger: [docs/thermodynamics/claim_ledger.yaml](claim_ledger.yaml)

Minimal verification pack:

```bash
python3 -m pytest tests/test_engine.py tests/test_thermodynamics.py tests/test_thermodynamic_evidence.py -vv
python3 experiments/verify_thermo_claims.py
python3 -m experiments.thermodynamic_eval \
	--benchmark-module remora.benchmarks.extended_v2_n500 \
	--results results/ablation_v2_n500_results.json \
	--calibration results/thermodynamic_calibration_n500.json \
	--output results/thermodynamic_eval_n500_calibrated_results.json
python3 -m experiments.thermodynamic_router_eval \
	--benchmark-module remora.benchmarks.extended_v2_n500 \
	--thermo-calibration results/thermodynamic_calibration_n500.json \
	--output results/thermodynamic_router_eval_n500_final_results.json
source .env.vars
python3 -m experiments.thermodynamic_router_eval \
	--benchmark-module remora.benchmarks.extended_v2_n500 \
	--thermo-calibration results/thermodynamic_calibration_n500.json \
	--evidence-worker-url "$CLOUDFLARE_WORKER_URL" \
	--output results/thermodynamic_router_eval_n500_evidence_results.json
```
