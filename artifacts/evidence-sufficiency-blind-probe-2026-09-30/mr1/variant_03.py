"""Evidence-sufficiency assessors (early-return style)."""

NE = "not_established"


def _holds(o, key):
    return key in o and o[key] is True


def _refuted(o, key):
    return key in o and o[key] is False


def _json_eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        return (isinstance(a, (int, float)) and isinstance(b, (int, float))
                and a == b)
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    if isinstance(a, list) or isinstance(b, list):
        if not (isinstance(a, list) and isinstance(b, list)):
            return False
        if len(a) != len(b):
            return False
        return all(_json_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) or isinstance(b, dict):
        if not (isinstance(a, dict) and isinstance(b, dict)):
            return False
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_json_eq(a[k], b[k]) for k in a)
    return False


def admission_accounting(o):
    if not (_holds(o, "effect_source_accepted") and _holds(o, "effect_seen")):
        return NE, "execution_observation_unaccepted_or_missing"
    if not _holds(o, "scope_accepted"):
        return NE, "scope_unaccepted_or_missing"
    if _holds(o, "admission_present"):
        if not _holds(o, "admission_source_accepted"):
            return NE, "admission_observation_unaccepted"
        if _holds(o, "admission_matches"):
            return "established", "covering_admission_observed_for_this_execution"
        return NE, "candidate_admission_does_not_establish_a_covering_admission"
    if o.get("admission_present") in (False, None):
        if not _holds(o, "mandatory_admission"):
            return NE, "admission_requirement_not_defined"
        if not _holds(o, "window_finalized"):
            return NE, "observation_window_open"
        if not _holds(o, "admission_coverage_complete"):
            return NE, "admission_coverage_incomplete"
        return "violated", "mandatory_admission_absent_in_complete_bounded_history"
    return NE, "admission_presence_unknown"


def tested_route_enforcement(o):
    if not _holds(o, "route_observation_accepted"):
        return NE, "route_observation_unaccepted_or_missing"
    if not _holds(o, "same_protected_operation"):
        return NE, "target_or_operation_not_bound"
    if not _holds(o, "outside_required_pep"):
        return NE, "alternative_route_not_established"
    if not _holds(o, "effect_observation_accepted"):
        return NE, "protected_effect_observation_unaccepted"
    if _holds(o, "protected_effect_observed"):
        return "violated", "accepted_effect_observed_outside_required_pep"
    if _refuted(o, "protected_effect_observed"):
        if not _holds(o, "effect_window_complete"):
            return NE, "no_effect_observation_not_complete"
        if not _holds(o, "valid_control_same_context"):
            return NE, "valid_control_missing_or_incomparable"
        if not _holds(o, "required_boundary_refusal_accepted"):
            return NE, "refusal_not_attributed_to_required_boundary"
        return "established", "named_route_refused_at_required_boundary_in_test_scope"
    return NE, "protected_effect_unknown"


def postcondition_observed(o):
    if not _holds(o, "readback_available"):
        return NE, "readback_unavailable"
    if not _holds(o, "source_accepted"):
        return NE, "readback_source_not_accepted"
    if not _holds(o, "same_target_and_predicate"):
        return NE, "target_or_predicate_not_bound"
    if not _holds(o, "fresh_in_declared_window"):
        return NE, "readback_stale_or_time_unbound"
    if not _holds(o, "settlement_reached"):
        return NE, "declared_settlement_point_not_reached"
    if "expected_state" not in o or "observed_state" not in o:
        return NE, "state_value_missing"
    if _json_eq(o["expected_state"], o["observed_state"]):
        return "established", "declared_postcondition_observed_at_named_point"
    return "violated", "declared_postcondition_disagreed_at_named_point"
