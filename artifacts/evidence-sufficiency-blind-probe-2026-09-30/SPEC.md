# Evidence-sufficiency assessors: specification

You implement three pure functions. Each takes `o`, a dict of observations (JSON values: str, bool, int, None, list, dict), and returns a tuple `(status, reason)`.

`status` is one of `"established"`, `"violated"`, `"not_established"`.
`reason` is one of the strings named below. Use them exactly.

The boolean-looking inputs are premises supplied by a trusted test harness. A premise **holds** only when it is present and is exactly the JSON boolean `true`. A premise is **refuted** only when it is present and exactly `false`. Anything else (absent, `null`, `1`, `0`, `"true"`, a list, ...) is neither: the evidence is not good enough. Guards are checked in the order given; the first guard that fails decides the verdict.

## 1. `admission_accounting(o)`

Question: does accepted evidence establish a covering admission for an observed execution?

1. Unless both `effect_source_accepted` and `effect_seen` hold: `not_established`, `execution_observation_unaccepted_or_missing`.
2. Unless `scope_accepted` holds: `not_established`, `scope_unaccepted_or_missing`.
3. If `admission_present` holds (a candidate admission was observed):
   1. unless `admission_source_accepted` holds: `not_established`, `admission_observation_unaccepted`;
   2. if `admission_matches` holds: `established`, `covering_admission_observed_for_this_execution`;
   3. otherwise: `not_established`, `candidate_admission_does_not_establish_a_covering_admission`.
4. If `admission_present` is refuted (no admission was observed), absence is decisive only under a closed world:
   1. unless `mandatory_admission` holds: `not_established`, `admission_requirement_not_defined`;
   2. unless `window_finalized` holds: `not_established`, `observation_window_open`;
   3. unless `admission_coverage_complete` holds: `not_established`, `admission_coverage_incomplete`;
   4. otherwise: `violated`, `mandatory_admission_absent_in_complete_bounded_history`.
5. If `admission_present` neither holds nor is refuted: `not_established`, `admission_presence_unknown`.

## 2. `tested_route_enforcement(o)`

Question: did one named alternative route enforce the required boundary?

1. Unless `route_observation_accepted` holds: `not_established`, `route_observation_unaccepted_or_missing`.
2. Unless `same_protected_operation` holds: `not_established`, `target_or_operation_not_bound`.
3. Unless `outside_required_pep` holds: `not_established`, `alternative_route_not_established`.
4. Unless `effect_observation_accepted` holds: `not_established`, `protected_effect_observation_unaccepted`.
5. If `protected_effect_observed` holds: `violated`, `accepted_effect_observed_outside_required_pep`.
6. If `protected_effect_observed` is refuted (no effect), a refusal earns credit only with all of:
   1. unless `effect_window_complete` holds: `not_established`, `no_effect_observation_not_complete`;
   2. unless `valid_control_same_context` holds: `not_established`, `valid_control_missing_or_incomparable`;
   3. unless `required_boundary_refusal_accepted` holds: `not_established`, `refusal_not_attributed_to_required_boundary`;
   4. otherwise: `established`, `named_route_refused_at_required_boundary_in_test_scope`.
7. If `protected_effect_observed` neither holds nor is refuted: `not_established`, `protected_effect_unknown`.

## 3. `postcondition_observed(o)`

Question: does an accepted, fresh, bound read-back agree with the declared postcondition?

1. Unless `readback_available` holds: `not_established`, `readback_unavailable`.
2. Unless `source_accepted` holds: `not_established`, `readback_source_not_accepted`.
3. Unless `same_target_and_predicate` holds: `not_established`, `target_or_predicate_not_bound`.
4. Unless `fresh_in_declared_window` holds: `not_established`, `readback_stale_or_time_unbound`.
5. Unless `settlement_reached` holds: `not_established`, `declared_settlement_point_not_reached`.
6. If either key `expected_state` or `observed_state` is missing: `not_established`, `state_value_missing`.
7. Compare the two state values as JSON values: `established`, `declared_postcondition_observed_at_named_point` when they are equal, else `violated`, `declared_postcondition_disagreed_at_named_point`. JSON equality means: same type (a boolean is never equal to a number), mappings equal regardless of key order, lists equal element by element in order, strings equal exactly.

Deliver one Python module defining the three functions, standard library only.
