"""Evidence-sufficiency assessors: rules as data, executed by a generic engine."""
import json

_RULES_JSON = r'''
{
  "admission_accounting": [
    {"require": ["effect_source_accepted", "effect_seen"],
     "else": ["not_established", "execution_observation_unaccepted_or_missing"]},
    {"require": ["scope_accepted"],
     "else": ["not_established", "scope_unaccepted_or_missing"]},
    {"branch": "admission_present",
     "holds": [
       {"require": ["admission_source_accepted"],
        "else": ["not_established", "admission_observation_unaccepted"]},
       {"require": ["admission_matches"],
        "else": ["not_established", "candidate_admission_does_not_establish_a_covering_admission"]},
       {"result": ["established", "covering_admission_observed_for_this_execution"]}
     ],
     "refuted": [
       {"require": ["mandatory_admission"],
        "else": ["not_established", "admission_requirement_not_defined"]},
       {"require": ["window_finalized"],
        "else": ["not_established", "observation_window_open"]},
       {"require": ["admission_coverage_complete"],
        "else": ["not_established", "admission_coverage_incomplete"]},
       {"result": ["violated", "mandatory_admission_absent_in_complete_bounded_history"]}
     ],
     "unknown": [
       {"result": ["not_established", "admission_presence_unknown"]}
     ]}
  ],
  "tested_route_enforcement": [
    {"require": ["route_observation_accepted"],
     "else": ["not_established", "route_observation_unaccepted_or_missing"]},
    {"require": ["same_protected_operation"],
     "else": ["not_established", "target_or_operation_not_bound"]},
    {"require": ["outside_required_pep"],
     "else": ["not_established", "alternative_route_not_established"]},
    {"require": ["effect_observation_accepted"],
     "else": ["not_established", "protected_effect_observation_unaccepted"]},
    {"branch": "protected_effect_observed",
     "holds": [
       {"result": ["violated", "accepted_effect_observed_outside_required_pep"]}
     ],
     "refuted": [
       {"require": ["effect_window_complete"],
        "else": ["not_established", "no_effect_observation_not_complete"]},
       {"require": ["valid_control_same_context"],
        "else": ["not_established", "valid_control_missing_or_incomparable"]},
       {"require": ["required_boundary_refusal_accepted"],
        "else": ["not_established", "refusal_not_attributed_to_required_boundary"]},
       {"result": ["established", "named_route_refused_at_required_boundary_in_test_scope"]}
     ],
     "unknown": [
       {"result": ["not_established", "protected_effect_unknown"]}
     ]}
  ],
  "postcondition_observed": [
    {"require": ["readback_available"],
     "else": ["not_established", "readback_unavailable"]},
    {"require": ["source_accepted"],
     "else": ["not_established", "readback_source_not_accepted"]},
    {"require": ["same_target_and_predicate"],
     "else": ["not_established", "target_or_predicate_not_bound"]},
    {"require": ["fresh_in_declared_window"],
     "else": ["not_established", "readback_stale_or_time_unbound"]},
    {"require": ["settlement_reached"],
     "else": ["not_established", "declared_settlement_point_not_reached"]},
    {"keys_present": ["expected_state", "observed_state"],
     "else": ["not_established", "state_value_missing"]},
    {"compare": ["expected_state", "observed_state"],
     "equal": ["established", "declared_postcondition_observed_at_named_point"],
     "differ": ["violated", "declared_postcondition_disagreed_at_named_point"]}
  ]
}
'''

RULES = json.loads(_RULES_JSON)


def _holds(o, key):
    return key in o and o[key] is True


def _refuted(o, key):
    return key in o and o[key] is False


def json_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, dict) or isinstance(b, dict):
        if not (isinstance(a, dict) and isinstance(b, dict)):
            return False
        if set(a.keys()) != set(b.keys()):
            return False
        return all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
            return False
        if len(a) != len(b):
            return False
        return sorted(map(repr, a)) == sorted(map(repr, b))
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    # numbers (int / float)
    return type(a) is type(b) and a == b or (
        isinstance(a, (int, float)) and isinstance(b, (int, float)) and a == b)


def _run(steps, o):
    for step in steps:
        if "require" in step:
            if not all(_holds(o, k) for k in step["require"]):
                return tuple(step["else"])
        elif "keys_present" in step:
            if not all(k in o for k in step["keys_present"]):
                return tuple(step["else"])
        elif "branch" in step:
            key = step["branch"]
            if _holds(o, key):
                sub = step["holds"]
            elif _refuted(o, key):
                sub = step["refuted"]
            else:
                sub = step["unknown"]
            return _run(sub, o)
        elif "compare" in step:
            ka, kb = step["compare"]
            if json_equal(o[ka], o[kb]):
                return tuple(step["equal"])
            return tuple(step["differ"])
        elif "result" in step:
            return tuple(step["result"])
        else:
            raise ValueError("bad rule step")
    raise ValueError("rules fell through")


def admission_accounting(o):
    return _run(RULES["admission_accounting"], o)


def tested_route_enforcement(o):
    return _run(RULES["tested_route_enforcement"], o)


def postcondition_observed(o):
    return _run(RULES["postcondition_observed"], o)
