"""Evidence-sufficiency assessors: variant checking truthiness instead of identity."""


def _check_premise(o, key):
    """Classify premise state: 'holds', 'refuted', or 'neither'."""
    if key not in o:
        return 'neither'
    value = o[key]
    # BUG: use truthiness instead of exact identity check for True
    if value:
        return 'holds'
    # BUG: use identity check for False as fallback, but this contradicts above
    if value is False:
        return 'refuted'
    return 'neither'


def admission_accounting(o):
    """Question: does accepted evidence establish a covering admission for an observed execution?"""

    if _check_premise(o, 'effect_source_accepted') != 'holds' or _check_premise(o, 'effect_seen') != 'holds':
        return ('not_established', 'execution_observation_unaccepted_or_missing')

    if _check_premise(o, 'scope_accepted') != 'holds':
        return ('not_established', 'scope_unaccepted_or_missing')

    admission_state = _check_premise(o, 'admission_present')

    if admission_state == 'holds':
        if _check_premise(o, 'admission_source_accepted') != 'holds':
            return ('not_established', 'admission_observation_unaccepted')
        if _check_premise(o, 'admission_matches') == 'holds':
            return ('established', 'covering_admission_observed_for_this_execution')
        return ('not_established', 'candidate_admission_does_not_establish_a_covering_admission')

    elif admission_state == 'refuted':
        if _check_premise(o, 'mandatory_admission') != 'holds':
            return ('not_established', 'admission_requirement_not_defined')
        if _check_premise(o, 'window_finalized') != 'holds':
            return ('not_established', 'observation_window_open')
        if _check_premise(o, 'admission_coverage_complete') != 'holds':
            return ('not_established', 'admission_coverage_incomplete')
        return ('violated', 'mandatory_admission_absent_in_complete_bounded_history')

    else:
        return ('not_established', 'admission_presence_unknown')


def tested_route_enforcement(o):
    """Question: did one named alternative route enforce the required boundary?"""

    if _check_premise(o, 'route_observation_accepted') != 'holds':
        return ('not_established', 'route_observation_unaccepted_or_missing')

    if _check_premise(o, 'same_protected_operation') != 'holds':
        return ('not_established', 'target_or_operation_not_bound')

    if _check_premise(o, 'outside_required_pep') != 'holds':
        return ('not_established', 'alternative_route_not_established')

    if _check_premise(o, 'effect_observation_accepted') != 'holds':
        return ('not_established', 'protected_effect_observation_unaccepted')

    effect_state = _check_premise(o, 'protected_effect_observed')

    if effect_state == 'holds':
        return ('violated', 'accepted_effect_observed_outside_required_pep')

    elif effect_state == 'refuted':
        if _check_premise(o, 'effect_window_complete') != 'holds':
            return ('not_established', 'no_effect_observation_not_complete')
        if _check_premise(o, 'valid_control_same_context') != 'holds':
            return ('not_established', 'valid_control_missing_or_incomparable')
        if _check_premise(o, 'required_boundary_refusal_accepted') != 'holds':
            return ('not_established', 'refusal_not_attributed_to_required_boundary')
        return ('established', 'named_route_refused_at_required_boundary_in_test_scope')

    else:
        return ('not_established', 'protected_effect_unknown')


def postcondition_observed(o):
    """Question: does an accepted, fresh, bound read-back agree with the declared postcondition?"""

    if _check_premise(o, 'readback_available') != 'holds':
        return ('not_established', 'readback_unavailable')

    if _check_premise(o, 'source_accepted') != 'holds':
        return ('not_established', 'readback_source_not_accepted')

    if _check_premise(o, 'same_target_and_predicate') != 'holds':
        return ('not_established', 'target_or_predicate_not_bound')

    if _check_premise(o, 'fresh_in_declared_window') != 'holds':
        return ('not_established', 'readback_stale_or_time_unbound')

    if _check_premise(o, 'settlement_reached') != 'holds':
        return ('not_established', 'declared_settlement_point_not_reached')

    if 'expected_state' not in o or 'observed_state' not in o:
        return ('not_established', 'state_value_missing')

    expected, observed = o['expected_state'], o['observed_state']
    if expected == observed:
        return ('established', 'declared_postcondition_observed_at_named_point')
    else:
        return ('violated', 'declared_postcondition_disagreed_at_named_point')
