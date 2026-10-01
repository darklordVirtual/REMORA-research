"""Evidence-sufficiency assessors: correct implementation."""


def _check_premise(o, key):
    """Classify premise state: 'holds', 'refuted', or 'neither'."""
    if key not in o:
        return 'neither'
    value = o[key]
    if value is True:
        return 'holds'
    if value is False:
        return 'refuted'
    return 'neither'


def admission_accounting(o):
    """Question: does accepted evidence establish a covering admission for an observed execution?"""

    # Guard 1: both effect_source_accepted and effect_seen must hold
    if _check_premise(o, 'effect_source_accepted') != 'holds' or _check_premise(o, 'effect_seen') != 'holds':
        return ('not_established', 'execution_observation_unaccepted_or_missing')

    # Guard 2: scope_accepted must hold
    if _check_premise(o, 'scope_accepted') != 'holds':
        return ('not_established', 'scope_unaccepted_or_missing')

    # Guard 3-5: dispatch on admission_present
    admission_state = _check_premise(o, 'admission_present')

    if admission_state == 'holds':
        # 3.1: admission_source_accepted must hold
        if _check_premise(o, 'admission_source_accepted') != 'holds':
            return ('not_established', 'admission_observation_unaccepted')
        # 3.2: if admission_matches holds
        if _check_premise(o, 'admission_matches') == 'holds':
            return ('established', 'covering_admission_observed_for_this_execution')
        # 3.3: otherwise
        return ('not_established', 'candidate_admission_does_not_establish_a_covering_admission')

    elif admission_state == 'refuted':
        # 4.1: mandatory_admission must hold
        if _check_premise(o, 'mandatory_admission') != 'holds':
            return ('not_established', 'admission_requirement_not_defined')
        # 4.2: window_finalized must hold
        if _check_premise(o, 'window_finalized') != 'holds':
            return ('not_established', 'observation_window_open')
        # 4.3: admission_coverage_complete must hold
        if _check_premise(o, 'admission_coverage_complete') != 'holds':
            return ('not_established', 'admission_coverage_incomplete')
        # 4.4: otherwise verdict is violation
        return ('violated', 'mandatory_admission_absent_in_complete_bounded_history')

    else:
        # Guard 5: neither holds nor is refuted
        return ('not_established', 'admission_presence_unknown')


def tested_route_enforcement(o):
    """Question: did one named alternative route enforce the required boundary?"""

    # Guard 1: route_observation_accepted must hold
    if _check_premise(o, 'route_observation_accepted') != 'holds':
        return ('not_established', 'route_observation_unaccepted_or_missing')

    # Guard 2: same_protected_operation must hold
    if _check_premise(o, 'same_protected_operation') != 'holds':
        return ('not_established', 'target_or_operation_not_bound')

    # Guard 3: outside_required_pep must hold
    if _check_premise(o, 'outside_required_pep') != 'holds':
        return ('not_established', 'alternative_route_not_established')

    # Guard 4: effect_observation_accepted must hold
    if _check_premise(o, 'effect_observation_accepted') != 'holds':
        return ('not_established', 'protected_effect_observation_unaccepted')

    # Guard 5-7: dispatch on protected_effect_observed
    effect_state = _check_premise(o, 'protected_effect_observed')

    if effect_state == 'holds':
        # Guard 5: effect observed is a violation
        return ('violated', 'accepted_effect_observed_outside_required_pep')

    elif effect_state == 'refuted':
        # 6.1: effect_window_complete must hold
        if _check_premise(o, 'effect_window_complete') != 'holds':
            return ('not_established', 'no_effect_observation_not_complete')
        # 6.2: valid_control_same_context must hold
        if _check_premise(o, 'valid_control_same_context') != 'holds':
            return ('not_established', 'valid_control_missing_or_incomparable')
        # 6.3: required_boundary_refusal_accepted must hold
        if _check_premise(o, 'required_boundary_refusal_accepted') != 'holds':
            return ('not_established', 'refusal_not_attributed_to_required_boundary')
        # 6.4: otherwise
        return ('established', 'named_route_refused_at_required_boundary_in_test_scope')

    else:
        # Guard 7: neither holds nor is refuted
        return ('not_established', 'protected_effect_unknown')


def postcondition_observed(o):
    """Question: does an accepted, fresh, bound read-back agree with the declared postcondition?"""

    # Guard 1: readback_available must hold
    if _check_premise(o, 'readback_available') != 'holds':
        return ('not_established', 'readback_unavailable')

    # Guard 2: source_accepted must hold
    if _check_premise(o, 'source_accepted') != 'holds':
        return ('not_established', 'readback_source_not_accepted')

    # Guard 3: same_target_and_predicate must hold
    if _check_premise(o, 'same_target_and_predicate') != 'holds':
        return ('not_established', 'target_or_predicate_not_bound')

    # Guard 4: fresh_in_declared_window must hold
    if _check_premise(o, 'fresh_in_declared_window') != 'holds':
        return ('not_established', 'readback_stale_or_time_unbound')

    # Guard 5: settlement_reached must hold
    if _check_premise(o, 'settlement_reached') != 'holds':
        return ('not_established', 'declared_settlement_point_not_reached')

    # Guard 6: both state values must be present
    if 'expected_state' not in o or 'observed_state' not in o:
        return ('not_established', 'state_value_missing')

    # Guard 7: compare as JSON values
    expected, observed = o['expected_state'], o['observed_state']
    if expected == observed:
        return ('established', 'declared_postcondition_observed_at_named_point')
    else:
        return ('violated', 'declared_postcondition_disagreed_at_named_point')
