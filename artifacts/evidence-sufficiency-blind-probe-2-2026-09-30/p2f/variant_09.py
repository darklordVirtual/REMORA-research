"""Evidence-sufficiency assessors (defensive implementation)."""

from typing import Any, Mapping, Optional, Tuple

Verdict = Tuple[str, str]

ESTABLISHED = "established"
VIOLATED = "violated"
NOT_ESTABLISHED = "not_established"

_MISSING = object()

# --- field names -----------------------------------------------------------
F_EFFECT_SOURCE_ACCEPTED = "effect_source_accepted"
F_EFFECT_SEEN = "effect_seen"
F_SCOPE_ACCEPTED = "scope_accepted"
F_ADMISSION_PRESENT = "admission_present"
F_ADMISSION_SOURCE_ACCEPTED = "admission_source_accepted"
F_ADMISSION_MATCHES = "admission_matches"
F_MANDATORY_ADMISSION = "mandatory_admission"
F_WINDOW_FINALIZED = "window_finalized"
F_ADMISSION_COVERAGE_COMPLETE = "admission_coverage_complete"

F_ROUTE_OBSERVATION_ACCEPTED = "route_observation_accepted"
F_SAME_PROTECTED_OPERATION = "same_protected_operation"
F_OUTSIDE_REQUIRED_PEP = "outside_required_pep"
F_EFFECT_OBSERVATION_ACCEPTED = "effect_observation_accepted"
F_PROTECTED_EFFECT_OBSERVED = "protected_effect_observed"
F_EFFECT_WINDOW_COMPLETE = "effect_window_complete"
F_VALID_CONTROL_SAME_CONTEXT = "valid_control_same_context"
F_REQUIRED_BOUNDARY_REFUSAL_ACCEPTED = "required_boundary_refusal_accepted"

F_READBACK_AVAILABLE = "readback_available"
F_SOURCE_ACCEPTED = "source_accepted"
F_SAME_TARGET_AND_PREDICATE = "same_target_and_predicate"
F_FRESH_IN_DECLARED_WINDOW = "fresh_in_declared_window"
F_SETTLEMENT_REACHED = "settlement_reached"
F_EXPECTED_STATE = "expected_state"
F_OBSERVED_STATE = "observed_state"

# --- reasons ---------------------------------------------------------------
R_EXEC_UNACCEPTED = "execution_observation_unaccepted_or_missing"
R_SCOPE_UNACCEPTED = "scope_unaccepted_or_missing"
R_ADMISSION_OBS_UNACCEPTED = "admission_observation_unaccepted"
R_COVERING_OBSERVED = "covering_admission_observed_for_this_execution"
R_CANDIDATE_NOT_COVERING = "candidate_admission_does_not_establish_a_covering_admission"
R_REQUIREMENT_NOT_DEFINED = "admission_requirement_not_defined"
R_WINDOW_OPEN = "observation_window_open"
R_COVERAGE_INCOMPLETE = "admission_coverage_incomplete"
R_MANDATORY_ABSENT = "mandatory_admission_absent_in_complete_bounded_history"
R_PRESENCE_UNKNOWN = "admission_presence_unknown"

R_ROUTE_UNACCEPTED = "route_observation_unaccepted_or_missing"
R_TARGET_OP_NOT_BOUND = "target_or_operation_not_bound"
R_ALT_ROUTE_NOT_ESTABLISHED = "alternative_route_not_established"
R_EFFECT_OBS_UNACCEPTED = "protected_effect_observation_unaccepted"
R_EFFECT_OUTSIDE_PEP = "accepted_effect_observed_outside_required_pep"
R_NO_EFFECT_INCOMPLETE = "no_effect_observation_not_complete"
R_CONTROL_MISSING = "valid_control_missing_or_incomparable"
R_REFUSAL_NOT_ATTRIBUTED = "refusal_not_attributed_to_required_boundary"
R_ROUTE_REFUSED = "named_route_refused_at_required_boundary_in_test_scope"
R_EFFECT_UNKNOWN = "protected_effect_unknown"

R_READBACK_UNAVAILABLE = "readback_unavailable"
R_READBACK_SOURCE = "readback_source_not_accepted"
R_TARGET_PRED_NOT_BOUND = "target_or_predicate_not_bound"
R_STALE = "readback_stale_or_time_unbound"
R_SETTLEMENT = "declared_settlement_point_not_reached"
R_STATE_MISSING = "state_value_missing"
R_POST_OBSERVED = "declared_postcondition_observed_at_named_point"
R_POST_DISAGREED = "declared_postcondition_disagreed_at_named_point"


# --- helpers ---------------------------------------------------------------
def _normalise(o: Any) -> Mapping[str, Any]:
    """Treat a non-mapping observation set as empty (nothing is proven)."""
    if isinstance(o, Mapping):
        return o
    return {}


def _get(o: Mapping[str, Any], key: str) -> Any:
    return o.get(key, _MISSING)


def _holds(o: Mapping[str, Any], key: str) -> bool:
    """A premise holds only when present and exactly JSON true."""
    return _get(o, key) is True


def _refuted(o: Mapping[str, Any], key: str) -> bool:
    """A premise is refuted only when present and exactly JSON false."""
    return _get(o, key) is False


def _all_hold(o: Mapping[str, Any], *keys: str) -> bool:
    return all(_holds(o, k) for k in keys)


def _first_unmet(o: Mapping[str, Any], guards) -> Optional[Verdict]:
    for key, reason in guards:
        if not _holds(o, key):
            return (NOT_ESTABLISHED, reason)
    return None


def _json_equal(a: Any, b: Any) -> bool:
    """Strict JSON equality: booleans never equal numbers, ordered lists."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if a is None or b is None:
        return a is None and b is None
    a_num = isinstance(a, (int, float))
    b_num = isinstance(b, (int, float))
    if a_num or b_num:
        return a_num and b_num and a == b
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    if isinstance(a, Mapping) or isinstance(b, Mapping):
        if not (isinstance(a, Mapping) and isinstance(b, Mapping)):
            return False
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_json_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
            return False
        if len(a) != len(b):
            return False
        return all(_json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


# --- assessors -------------------------------------------------------------
def admission_accounting(o) -> Verdict:
    o = _normalise(o)
    if not _all_hold(o, F_EFFECT_SOURCE_ACCEPTED, F_EFFECT_SEEN):
        return (NOT_ESTABLISHED, R_EXEC_UNACCEPTED)
    if not _holds(o, F_SCOPE_ACCEPTED):
        return (NOT_ESTABLISHED, R_SCOPE_UNACCEPTED)
    if _holds(o, F_ADMISSION_PRESENT):
        if not _holds(o, F_ADMISSION_SOURCE_ACCEPTED):
            return (NOT_ESTABLISHED, R_ADMISSION_OBS_UNACCEPTED)
        if _holds(o, F_ADMISSION_MATCHES):
            return (ESTABLISHED, R_COVERING_OBSERVED)
        return (NOT_ESTABLISHED, R_CANDIDATE_NOT_COVERING)
    if _refuted(o, F_ADMISSION_PRESENT):
        unmet = _first_unmet(o, (
            (F_MANDATORY_ADMISSION, R_REQUIREMENT_NOT_DEFINED),
            (F_WINDOW_FINALIZED, R_WINDOW_OPEN),
            (F_ADMISSION_COVERAGE_COMPLETE, R_COVERAGE_INCOMPLETE),
        ))
        if unmet is not None:
            return unmet
        return (VIOLATED, R_MANDATORY_ABSENT)
    return (NOT_ESTABLISHED, R_PRESENCE_UNKNOWN)


def tested_route_enforcement(o) -> Verdict:
    o = _normalise(o)
    unmet = _first_unmet(o, (
        (F_ROUTE_OBSERVATION_ACCEPTED, R_ROUTE_UNACCEPTED),
        (F_SAME_PROTECTED_OPERATION, R_TARGET_OP_NOT_BOUND),
        (F_OUTSIDE_REQUIRED_PEP, R_ALT_ROUTE_NOT_ESTABLISHED),
    ))
    if unmet is not None:
        return unmet
    if _holds(o, F_PROTECTED_EFFECT_OBSERVED):
        return (VIOLATED, R_EFFECT_OUTSIDE_PEP)
    if not _holds(o, F_EFFECT_OBSERVATION_ACCEPTED):
        return (NOT_ESTABLISHED, R_EFFECT_OBS_UNACCEPTED)
    if _refuted(o, F_PROTECTED_EFFECT_OBSERVED):
        unmet = _first_unmet(o, (
            (F_EFFECT_WINDOW_COMPLETE, R_NO_EFFECT_INCOMPLETE),
            (F_VALID_CONTROL_SAME_CONTEXT, R_CONTROL_MISSING),
            (F_REQUIRED_BOUNDARY_REFUSAL_ACCEPTED, R_REFUSAL_NOT_ATTRIBUTED),
        ))
        if unmet is not None:
            return unmet
        return (ESTABLISHED, R_ROUTE_REFUSED)
    return (NOT_ESTABLISHED, R_EFFECT_UNKNOWN)


def postcondition_observed(o) -> Verdict:
    o = _normalise(o)
    unmet = _first_unmet(o, (
        (F_READBACK_AVAILABLE, R_READBACK_UNAVAILABLE),
        (F_SOURCE_ACCEPTED, R_READBACK_SOURCE),
        (F_SAME_TARGET_AND_PREDICATE, R_TARGET_PRED_NOT_BOUND),
        (F_FRESH_IN_DECLARED_WINDOW, R_STALE),
        (F_SETTLEMENT_REACHED, R_SETTLEMENT),
    ))
    if unmet is not None:
        return unmet
    expected = _get(o, F_EXPECTED_STATE)
    observed = _get(o, F_OBSERVED_STATE)
    if expected is _MISSING or observed is _MISSING:
        return (NOT_ESTABLISHED, R_STATE_MISSING)
    if _json_equal(expected, observed):
        return (ESTABLISHED, R_POST_OBSERVED)
    return (VIOLATED, R_POST_DISAGREED)
