# TaskIntent Authority — v1

**Status:** pre-registered (2026-08-04)  
**Implements:** Gate 1 criterion 1A; "TaskIntent source defined"  
**Code reference:** `remora/toolcall/routing/goal_match.py`, `EFFECT_VOCABULARY_VERSION = "v1"`

---

## 1. The problem

`match_tool_to_intent` accepts a `TaskIntent` that may be produced by a model.
The function's invariant (*a model may propose an intent, but may not thereby
assert SUPPORTED*) is only maintained if the verification clauses are
re-derivable from sources other than the model's word.

Two authority gaps existed before this document:

1. Source-span gap (closed 2026-08-04, §36): `source_spans` verified entity
   text presence but not effect grounding. Fixed by adding `action_spans` +
   `EFFECT_VOCABULARY v1` + negation/conditionality detection.

2. Provenance gap (this document): no definition of where a `TaskIntent`
   should come from at runtime. Without it, any caller can supply any intent
   and the system cannot distinguish a signed work order from a model hallucination.

---

## 2. Two legitimate sources

### 2.1 Primary source: signed structured workflow-intent (strong authority)

A `TaskIntent` is **authoritative** when it originates from a source that is
outside the model's control and was not constructed by reading the proposed
call:

| Source | Example |
|--------|---------|
| Signed work order | `work_order.signed_json` from the CMMS |
| Operator form submission | validated API POST from the HMI |
| Approved workflow template | deployment-defined, version-locked |
| Signed task envelope | cryptographically bound to the session |

Construction rule for primary source:

```python
TaskIntent(
    operation="close",
    resource_type="work_order",
    requested_effect="close",
    target_entities=("target_resource",),
    source_spans=("<work_order_id_from_signed_doc>",),
    action_spans=("<action_verb_from_signed_doc>",),
    proposed_by="signed_work_order:<doc_hash>",
)
```

A primary-source intent **may** establish SUPPORTED, subject to the normal
verification clauses in `match_tool_to_intent`.

### 2.2 Secondary source: model-proposed intent from free text (proposal only)

A model may extract a `TaskIntent` from user text. This extraction **does not
grant authority**: the model's output is the input to `match_tool_to_intent`,
not a bypass of it. All verification clauses apply.

Minimum requirements for a model-proposed intent to be submitted:

- `source_spans`: verbatim text from the user task that names the entity
- `action_spans`: verbatim text from the user task that contains an
  unambiguous action keyword per `EFFECT_VOCABULARY/v1`
- `proposed_by`: must identify the model version and extraction prompt
  version, e.g. `"llm:llama-3.3-70b/prompt-v2"`
- Action spans must NOT include negated or conditional constructs; a model
  that cannot isolate an unambiguous action span must leave `action_spans=()`
  rather than submit a negated or conditional span

A model-proposed intent without valid `action_spans` yields UNKNOWN, never
SUPPORTED. This is not a defect; it is the honest result when the text is
ambiguous.

### 2.3 What neither source can do

Regardless of origin, a `TaskIntent`:

- **Cannot** set `tool_matches_goal=True` directly; the field is computed by
  `match_tool_to_intent`, not supplied by the intent producer
- **Cannot** grant SUPPORTED to a call that fails the resource, effect, or
  role verification clauses
- **Cannot** make an unrecognised effect name groundable; effects not in
  `EFFECT_VOCABULARY/v1` yield UNKNOWN
- **Cannot** be delivered inside the tool call request
- **Cannot** be modified by the agent after the context builder freezes it

---

## 3. UNKNOWN rules

The following intent states yield UNKNOWN, never SUPPORTED:

| Condition | Reason |
|-----------|--------|
| `action_spans` is empty | Effect ungrounded |
| `action_spans` not found verbatim in task text | Intent unverified |
| Action span keyword preceded by negation word | Negated request |
| Action span keyword preceded by conditional marker | Conditional — not immediate |
| `requested_effect` not in `EFFECT_VOCABULARY/v1` | Effect ungroundable |
| `source_spans` not found verbatim in task text | Entity unverified |
| `proposed_by` unspecified and not primary source | Provenance unknown |

---

## 4. Effect vocabulary version

The current vocabulary is `EFFECT_VOCABULARY_VERSION = "v1"` (2026-08-04).
The vocabulary is frozen in `remora/toolcall/routing/goal_match.py`. Any
change to the vocabulary must:

1. Increment the version string
2. Create a dated entry in `NEGATIVE_RESULTS.md` if the change affects
   previously-UNKNOWN verdicts
3. Be recorded in the commit that changes it

---

## 5. Relation to SHELF-020 and Gate 1

`match_tool_to_intent` runs in both paths since 2026-08-04: the
research/benchmark path (`build_full_observation` directly) and
`/v1/execution`, which builds its observation through the same function
whenever `REMORA_SEMANTIC_BUNDLE_MODULE` is configured
(`remora/toolcall/semantic_bundle.py`). The intent enters the execution path
only as an opaque `intent_ref` resolved server-side against a source declared
in §2; never inside the tool-call request, per §2.3.

**Gate 1 acceptance status (this criterion):** ✓ defined and documented here.  
**SHELF-020 closure criterion:** ✓ met 2026-08-04; `/v1/execution/assess`
calls `build_full_observation` with a registered, hashed contract bundle and
an intent resolved from a declared source; Parity 4 in
`tests/test_shelf020_parity.py` and `tests/test_execution_semantic_wiring.py`
pin it. Without a configured bundle, `tool_matches_goal` remains `None` in the
execution path (authoritative absence, not a fabricated signal), and no
request field can set it.
