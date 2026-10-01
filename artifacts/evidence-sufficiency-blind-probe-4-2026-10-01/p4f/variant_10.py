"""Evidence-sufficiency assessors (validation-first)."""
from typing import Any, NamedTuple

HOLDS = "holds"
REFUTED = "refuted"
UNKNOWN = "unknown"

_MISSING = object()


def _get(o, key):
    if not isinstance(o, dict):
        return _MISSING
    return o[key] if key in o else _MISSING


def _tri(o, key):
    v = _get(o, key)
    if v is _MISSING:
        return UNKNOWN
    if v is True:
        return HOLDS
    if v is False:
        return REFUTED
    return UNKNOWN


def _json_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, str):
        return isinstance(b, str) and a == b
    if a is None:
        return b is None
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return isinstance(b, dict) and set(a) == set(b) and all(_json_equal(a[k], b[k]) for k in a)
    return False


class AdmissionRecord(NamedTuple):
    effect_source: str
    effect_seen: str
    scope: str
    present: str
    adm_source: str
    matches: str
    mandatory: str
    finalized: str
    coverage: str


def _read_admission(o):
    return AdmissionRecord(
        effect_source=_tri(o, "effect_source_accepted"),
        effect_seen=_tri(o, "effect_seen"),
        scope=_tri(o, "scope_accepted"),
        present=_tri(o, "admission_present"),
        adm_source=_tri(o, "admission_source_accepted"),
        matches=_tri(o, "admission_matches"),
        mandatory=_tri(o, "mandatory_admission"),
        finalized=_tri(o, "window_finalized"),
        coverage=_tri(o, "admission_coverage_complete"),
    )


def admission_accounting(o):
    r = _read_admission(o)
    if not (r.effect_source == HOLDS and r.effect_seen == HOLDS):
        return ("not_established", "execution_observation_unaccepted_or_missing")
    if r.scope != HOLDS:
        return ("not_established", "scope_unaccepted_or_missing")
    if r.present == HOLDS:
        if r.adm_source != HOLDS:
            return ("not_established", "admission_observation_unaccepted")
        if r.matches == HOLDS:
            return ("established", "covering_admission_observed_for_this_execution")
        return ("not_established", "candidate_admission_does_not_establish_a_covering_admission")
    if r.present == REFUTED:
        if r.mandatory != HOLDS:
            return ("not_established", "admission_requirement_not_defined")
        if r.finalized != HOLDS:
            return ("not_established", "observation_window_open")
        if r.coverage != HOLDS:
            return ("not_established", "admission_coverage_incomplete")
        return ("violated", "mandatory_admission_absent_in_complete_bounded_history")
    return ("not_established", "admission_presence_unknown")


class RouteRecord(NamedTuple):
    route_obs: str
    same_op: str
    outside_pep: str
    effect_obs: str
    effect_observed: str
    window: str
    control: str
    refusal: str


def _read_route(o):
    return RouteRecord(
        route_obs=_tri(o, "route_observation_accepted"),
        same_op=_tri(o, "same_protected_operation"),
        outside_pep=_tri(o, "outside_required_pep"),
        effect_obs=_tri(o, "effect_observation_accepted"),
        effect_observed=_tri(o, "protected_effect_observed"),
        window=_tri(o, "effect_window_complete"),
        control=_tri(o, "valid_control_same_context"),
        refusal=_tri(o, "required_boundary_refusal_accepted"),
    )


def tested_route_enforcement(o):
    r = _read_route(o)
    if r.route_obs != HOLDS:
        return ("not_established", "route_observation_unaccepted_or_missing")
    if r.same_op != HOLDS:
        return ("not_established", "target_or_operation_not_bound")
    if r.outside_pep != HOLDS:
        return ("not_established", "alternative_route_not_established")
    if r.effect_obs != HOLDS:
        return ("not_established", "protected_effect_observation_unaccepted")
    if r.effect_observed == HOLDS:
        return ("violated", "accepted_effect_observed_outside_required_pep")
    if r.effect_observed == REFUTED:
        if r.window != HOLDS:
            return ("not_established", "no_effect_observation_not_complete")
        if r.control != HOLDS:
            return ("not_established", "valid_control_missing_or_incomparable")
        if r.refusal != HOLDS:
            return ("not_established", "refusal_not_attributed_to_required_boundary")
        return ("established", "named_route_refused_at_required_boundary_in_test_scope")
    return ("not_established", "protected_effect_unknown")


class PostRecord(NamedTuple):
    readback: str
    source: str
    bound: str
    fresh: str
    settled: str
    has_expected: bool
    has_observed: bool
    expected: Any
    observed: Any


def _read_post(o):
    e = _get(o, "expected_state")
    b = _get(o, "observed_state")
    return PostRecord(
        readback=_tri(o, "readback_available"),
        source=_tri(o, "source_accepted"),
        bound=_tri(o, "same_target_and_predicate"),
        fresh=_tri(o, "fresh_in_declared_window"),
        settled=_tri(o, "settlement_reached"),
        has_expected=e is not _MISSING and e is not None,
        has_observed=b is not _MISSING and b is not None,
        expected=None if e is _MISSING else e,
        observed=None if b is _MISSING else b,
    )


def postcondition_observed(o):
    r = _read_post(o)
    if r.readback != HOLDS:
        return ("not_established", "readback_unavailable")
    if r.source != HOLDS:
        return ("not_established", "readback_source_not_accepted")
    if r.bound != HOLDS:
        return ("not_established", "target_or_predicate_not_bound")
    if r.fresh != HOLDS:
        return ("not_established", "readback_stale_or_time_unbound")
    if r.settled != HOLDS:
        return ("not_established", "declared_settlement_point_not_reached")
    if not (r.has_expected and r.has_observed):
        return ("not_established", "state_value_missing")
    if _json_equal(r.expected, r.observed):
        return ("established", "declared_postcondition_observed_at_named_point")
    return ("violated", "declared_postcondition_disagreed_at_named_point")
