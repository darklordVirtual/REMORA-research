# Jev as a decision provider

Status: experimental. The adapter has been exercised against the documented
request and response shapes only. It has not been run against the live
service from this repository, and nothing on this page is evidence about the
model's answers, latency or availability.

## The one rule

A decision provider may inform a decision. It may never create authority.

Jev answers narrow, typed questions about a proposed call with calibrated
probabilities. REMORA admits those answers through one boundary,
`remora.decision_providers.enrich.enrich`, and that boundary can do exactly
two things. It can add a favourable model signal, which the engine reads on
its evidence path. It can raise the `adversarial_detected` flag, which the
deterministic hard block escalates. It cannot write a deployment fact, it
cannot lower a flag, and it cannot name a route.

Under the execution profile, no combination of model signals reaches ACCEPT.
That invariant predates this integration and is pinned by
`tests/test_policy_whatif.py`. The integration inherits it by construction,
because the projection is confined to the model-signal class. On an engine
configured without the execution profile the bound does not hold, and
`tests/test_decision_providers.py` records that limit as a test so it cannot
change quietly.

## What is sent

`semantic_state` builds the state a provider sees: the stated intent, the tool
name, the arguments, and any declared context. A key whose name suggests a
credential is refused rather than redacted. Production credentials, tokens and
session identifiers have no bearing on a semantic question and must never
appear in a provider's logs.

## What is asked

`remora.decision_providers.questions.REMORA_QUESTIONS_V1`, versioned as
`remora-semantic-v1`. Six questions, each answerable from the minimised state
alone.

| Question | Kind | Admitted as |
|---|---|---|
| `intent_match` | probability | favourable evidence signal, with `target_matches_request` |
| `target_matches_request` | probability | favourable evidence signal, with `intent_match` |
| `possible_injection` | probability | `adversarial_detected` raised above threshold |
| `scope_drift` | probability | withholds the favourable signal above threshold |
| `action_reversibility` | score on a legend | recorded only |
| `semantic_risk` | score on a legend | recorded only |

The last two are recorded in the evidence and never projected. The observation
fields that look right for them, `risk_tier` and `rollback_available`, are
deployment facts. They are kept in the evidence so a calibration study can
compare the model's view with the deployment's declaration.

There is no `recommended_route` question. A model that names a route starts to
look like the thing that decides, and the routing literals leak into logs as
if they were decisions. The engine computes the route from the signals.

## Thresholds have no defaults

`SemanticThresholds` requires every cut to be supplied. A threshold is a
calibrated policy decision, and a default would make the most consequential
number in the integration the one nobody reviewed.

Calibrate against a corpus in the deployment's language. TypeSafe states that
English is the primary language with the best accuracy and recommends separate
testing for others. A threshold tuned on English prompts is not evidence about
Norwegian ones. Record the corpus hash and the question-set version beside the
thresholds in configuration, and re-run calibration when either changes.

## Failure is structural

A provider that cannot answer raises `DecisionProviderError`, and `enrich`
returns the observation untouched with outcome `provider_unavailable`. The
engine then makes the deterministic decision.

No per-tier failure table is offered. A provider can only add a favourable
signal or raise a flag, so the decision without the provider is never more
permissive than the decision with it. A table would be a place to configure a
fail-open, and there is nothing it could express that is safe.

Model availability therefore affects automation coverage. It never affects the
safety boundary.

## Cloudflare Workers AI

`remora.decision_providers.cloudflare.CloudflareJevProvider` reaches the model
at `POST /accounts/{account}/ai/run` with model id `typesafe/jev`. Routing
through the Cloudflare account means no separate vendor key.

Environment: `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_AI_GATEWAY_ID`. The token is registered in
`docs/assurance/credential_topology.yaml` as an oracle credential, because
the adapter dispatches no governed tool. If a governed tool ever dispatches
through that token, the entry must move to `effect_credential`, as its own
note states.

## Billing is the one operational prerequisite

Learned by running the adapter against the live service on 2026-09-24, and
recorded here so nobody rediscovers it at 402. `typesafe/jev` is a partner
model. It is paid for from prepaid AI Gateway credits (Unified Billing), not
from the Workers AI standard plan. Without credits the service answers
`HTTP 402` with code `2021`: "Insufficient balance; add money to your
gateway or use BYOK".

In the same session the account token, the endpoint and the request shape
were all confirmed correct: a native Workers AI model on the same `/ai/run`
endpoint answered `200`. The adapter surfaces the Cloudflare message in
`DecisionProviderError`, so the operational cause is visible in the refusal
rather than hidden behind a status code.

Three steps make the call billable.

1. Load credits in the dashboard: AI Gateway, Credits Available, Manage,
   Top-up credits. A payment method is required and Cloudflare adds a 5 %
   fee to purchased credits. There is no API for this step.
2. Set the gateway's Workers AI billing to Unified billing, in the gateway
   settings or by a `PUT` on the gateway with
   `workers_ai_billing_mode: "unified"`.
3. Name that gateway in `CLOUDFLARE_AI_GATEWAY_ID`. The adapter sends it as
   the documented `cf-aig-gateway-id` header, which is what routes the spend
   to the credit balance and gives the request analytics and rate limiting.
4. Mint a token with the AI Gateway Run permission from the gateway's
   settings ("Create authentication token") and set it as
   `CLOUDFLARE_AI_GATEWAY_TOKEN`. Unified Billing refuses the run call
   without it, with `HTTP 403` code `2049`. An account token with Workers AI
   and AI Gateway read and edit rights does not carry Run. Cloudflare scopes
   Run to the whole account, not to one gateway, so treat the token as able
   to send through every gateway you own.

The gateway `remora-jev` was created on 2026-09-24 with Unified billing and
authentication on, so steps two and three are done for this account. Steps
one and four are dashboard actions.

The alternative is BYOK: store a TypeSafe API key on the gateway, and the
request is billed by TypeSafe directly.

At the published price of $0.042 per million input tokens, a state of two
thousand tokens costs about $0.00008 per decision. Ten dollars of credit is
more than a hundred thousand decisions.

Three response details are preserved rather than simplified. A `noul` answer
is a probability and stays one; `DecisionAnswer.as_bool` demands an explicit
threshold. A `score` answer indexes its legend in the legend's units, and
value and labels travel together. The resolved model version comes from the
response, not from the alias in the request, so an alias repointed upstream is
visible in the record.

## Example

```python
from remora.decision_providers.cloudflare import CloudflareJevProvider
from remora.decision_providers.enrich import SemanticThresholds, enrich, semantic_state
from remora.decision_providers.questions import QUESTION_SET_VERSION
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation

provider = CloudflareJevProvider(question_set_version=QUESTION_SET_VERSION)

# From reviewed configuration, calibrated against a corpus in the deployment's language.
thresholds = SemanticThresholds(
    intent_match=0.85,
    target_matches_request=0.85,
    possible_injection=0.5,
    scope_drift=0.5,
)

state = semantic_state(
    intent="Change VLAN on the access port for customer C123 from 410 to 420",
    tool_name="access.change_customer_vlan",
    arguments={"customer_id": "C123", "port": "osl-rtr-07/1/12", "vlan": 420},
)

observation = PolicyObservation(
    question=state["intent"],
    risk_tier="high",
    action_type="configuration_change",
    target_environment="prod",
)

result = enrich(observation, provider, state=state, thresholds=thresholds)
decision = RemoraDecisionEngine(execution_profile=True).decide(result.observation)

# result.evidence carries the answers, the resolved model and the state hash.
# result.notes carries one line per admission decision, for the audit record.
```

The evidence record is returned to the caller rather than written into the
decision envelope. The envelope's bytes are what every historical token and
lease was signed over, and they are not rewritten for a new input class.
Record the evidence beside the decision, joined by the proposal identity.

## What this is not

It is not a benchmark result. No measurement of Jev against the existing
oracle corpus exists in this repository yet, and the comparison should be run
before any claim about replacing an oracle is made.

It is not a production gate. Nothing in the shipped execution path calls
`enrich`. Wiring it into a governed dispatch is a separate change with its
own review, and it should follow the calibration study rather than precede it.
