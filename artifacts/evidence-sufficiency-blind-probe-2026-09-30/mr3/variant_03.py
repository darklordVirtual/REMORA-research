"""Evidence-sufficiency assessors (nested-conditional style)."""

NE = "not_established"
EST = "established"
VIO = "violated"


def _holds(o, key):
    return key in o and o[key] is True


def _refuted(o, key):
    return key in o and o[key] is False


def _json_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        for x, y in zip(a, b):
            if not _json_equal(x, y):
                return False
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        for k in a:
            if not _json_equal(a[k], b[k]):
                return False
        return True
    return False


def admission_accounting(o):
    effect_ok = _holds(o, "effect_source_accepted") and _holds(o, "effect_seen")
    scope_ok = _holds(o, "scope_accepted")
    present_holds = _holds(o, "admission_present")
    present_refuted = _refuted(o, "admission_present")
    source_ok = _holds(o, "admission_source_accepted")
    matches = _holds(o, "admission_matches")
    mandatory = _holds(o, "mandatory_admission")
    finalized = _holds(o, "window_finalized")
    coverage = _holds(o, "admission_coverage_complete")

    if not effect_ok:
        result = (NE, "execution_observation_unaccepted_or_missing")
    elif not scope_ok:
        result = (NE, "scope_unaccepted_or_missing")
    elif present_holds:
        if not source_ok:
            result = (NE, "admission_observation_unaccepted")
        elif matches:
            result = (EST, "covering_admission_observed_for_this_execution")
        else:
            result = (NE, "candidate_admission_does_not_establish_a_covering_admission")
    elif present_refuted:
        if not finalized:
            result = (NE, "observation_window_open")
        elif not mandatory:
            result = (NE, "admission_requirement_not_defined")
        elif not coverage:
            result = (NE, "admission_coverage_incomplete")
        else:
            result = (VIO, "mandatory_admission_absent_in_complete_bounded_history")
    else:
        result = (NE, "admission_presence_unknown")
    return result


def tested_route_enforcement(o):
    route_ok = _holds(o, "route_observation_accepted")
    same_op = _holds(o, "same_protected_operation")
    outside = _holds(o, "outside_required_pep")
    effect_obs_ok = _holds(o, "effect_observation_accepted")
    effect_holds = _holds(o, "protected_effect_observed")
    effect_refuted = _refuted(o, "protected_effect_observed")
    window_complete = _holds(o, "effect_window_complete")
    control_ok = _holds(o, "valid_control_same_context")
    refusal_ok = _holds(o, "required_boundary_refusal_accepted")

    if not route_ok:
        result = (NE, "route_observation_unaccepted_or_missing")
    elif not same_op:
        result = (NE, "target_or_operation_not_bound")
    elif not outside:
        result = (NE, "alternative_route_not_established")
    elif not effect_obs_ok:
        result = (NE, "protected_effect_observation_unaccepted")
    elif effect_holds:
        result = (VIO, "accepted_effect_observed_outside_required_pep")
    elif effect_refuted:
        if not window_complete:
            result = (NE, "no_effect_observation_not_complete")
        elif not control_ok:
            result = (NE, "valid_control_missing_or_incomparable")
        elif not refusal_ok:
            result = (NE, "refusal_not_attributed_to_required_boundary")
        else:
            result = (EST, "named_route_refused_at_required_boundary_in_test_scope")
    else:
        result = (NE, "protected_effect_unknown")
    return result


def postcondition_observed(o):
    available = _holds(o, "readback_available")
    source_ok = _holds(o, "source_accepted")
    bound = _holds(o, "same_target_and_predicate")
    fresh = _holds(o, "fresh_in_declared_window")
    settled = _holds(o, "settlement_reached")
    states_present = "expected_state" in o and "observed_state" in o

    if not available:
        result = (NE, "readback_unavailable")
    elif not source_ok:
        result = (NE, "readback_source_not_accepted")
    elif not bound:
        result = (NE, "target_or_predicate_not_bound")
    elif not fresh:
        result = (NE, "readback_stale_or_time_unbound")
    elif not settled:
        result = (NE, "declared_settlement_point_not_reached")
    elif not states_present:
        result = (NE, "state_value_missing")
    else:
        if _json_equal(o["expected_state"], o["observed_state"]):
            result = (EST, "declared_postcondition_observed_at_named_point")
        else:
            result = (VIO, "declared_postcondition_disagreed_at_named_point")
    return result
