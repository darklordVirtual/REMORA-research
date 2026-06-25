# Limitations

The v4 thermodynamic layer is real code with real artifacts, but several stronger statements remain unsupported.

Still unsupported or only partial:

- `χ` as a robust live per-item fragility law
- routing superiority at full coverage over majority voting
- strong end-to-end superiority of a thermodynamic guardrail plus evidence-backfill policy: the calibrated N500 evidence-backed run is positive over majority, but only modestly and with heavy dependence on external evidence
- hallucination bound as a theorem or robust empirical upper bound
- universal phase-transition claims for LLM consensus
- first-principles derivation of the temperature law

Current status of major terms:

- `F(T) = λD - T·H`: implemented proxy
- `V = H + λD`: historical Lyapunov potential, not the same object as `F(T)`
- `χ`: useful offline harm proxy, not yet robustly live-validated
- `hallucination_bound()`: calibrated risk proxy / conjectural bound, not a proof
- enforced thermodynamic guardrail: calibrated N500 artifact is now selectively useful (`coverage=0.182`, `accuracy_on_answered=0.8687`, `majority_error_intercept_rate=0.9594`) but still not a full benchmark routing win

Not currently implemented as production thermodynamic modules:

- heat capacity `C_V`
- partition function `Z`
- correlation length `ξ`
- entropy production `σ_s`
- Maxwell construction
- FDT-based susceptibility estimator
- renormalization-group scaling

These should be presented as roadmap or future work, not current REMORA capability.
