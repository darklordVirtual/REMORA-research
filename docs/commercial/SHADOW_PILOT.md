# REMORA Shadow Pilot

The Shadow Pilot is the primary sellable offering at the current release
profile (`SHADOW_PILOT` in
[`../assurance/release_profiles_v1.yaml`](../assurance/release_profiles_v1.yaml)).
REMORA observes and decides; it never enforces. The pilot's deliverable is
**evidence**: what governance would have done on the customer's real agent
actions, with tamper-evident records.

## Customer lifecycle

1. **Discovery** — scope the agent surfaces, action classes and risk appetite.
2. **Tool inventory** — enumerate the tools agents can invoke, their effects
   and blast radius.
3. **ToolSpec definition** — deployment-owned Signed ToolSpec entries: tool
   meaning, target, risk and approved intent come from the deployment, never
   from the calling agent.
4. **Policy mapping** — map the customer's rules onto deterministic hard
   guards and conditional gates; policy identity is hashed and recorded.
5. **Shadow deployment** — the action stream is mirrored through
   `/v1/execution/assess`; every decision lands in the per-tenant audit chain.
6. **Ground-truth evaluation** — the customer labels a sample of actions;
   REMORA's decisions are scored against those labels (false-accept rate,
   review routing quality, friction).
7. **Evidence report** — decision distributions, counterfactual deltas,
   chain-verification results, and every negative finding included.
8. **Go / no-go** — the customer decides whether the measured behavior
   justifies moving toward enforcement.
9. **Controlled-enforcement roadmap** — if go: the register-gated path in
   `PRODUCT_PACKAGING.md` (REM-020/021/022/023 closed, capability ladder
   raised) before any action is ever blocked or executed by REMORA.

## What the pilot explicitly does not do

- It does not block, modify or execute any customer action.
- It does not require customer credentials to downstream systems.
- It does not assert safety guarantees beyond what the claim register backs;
  negative results (`NEGATIVE_RESULTS.md`) travel with the evidence report.

## Exit criteria

A pilot is complete when the evidence report exists, its audit chain
verifies, ground-truth scoring is reproducible from the archived artifacts,
and the go/no-go decision is recorded.
