"""Evidence-sufficiency assessors, object-oriented implementation."""

EST, VIO, NOT = "established", "violated", "not_established"


def _holds(o, key):
    return key in o and o[key] is True


def _refuted(o, key):
    return key in o and o[key] is False


def _json_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, dict) or isinstance(b, dict):
        if not (isinstance(a, dict) and isinstance(b, dict)):
            return False
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) or isinstance(b, list):
        if not (isinstance(a, list) and isinstance(b, list)):
            return False
        if len(a) != len(b):
            return False
        return all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    return a == b


class Guard:
    def __init__(self, keys, reason):
        self.keys = [keys] if isinstance(keys, str) else list(keys)
        self.reason = reason

    def passes(self, o):
        return all(_holds(o, k) for k in self.keys)


class Assessor:
    guards = ()

    def assess(self, o):
        for g in self.guards:
            if not g.passes(o):
                return NOT, g.reason
        return self.decide(o)

    def decide(self, o):
        raise NotImplementedError


class AdmissionAccounting(Assessor):
    guards = (
        Guard(["effect_source_accepted", "effect_seen"],
              "execution_observation_unaccepted_or_missing"),
        Guard("scope_accepted", "scope_unaccepted_or_missing"),
    )

    def decide(self, o):
        if _holds(o, "admission_present"):
            return self._present(o)
        if _refuted(o, "admission_present"):
            return self._absent(o)
        return NOT, "admission_presence_unknown"

    def _present(self, o):
        if not _holds(o, "admission_source_accepted"):
            return NOT, "admission_observation_unaccepted"
        if _holds(o, "admission_matches"):
            return EST, "covering_admission_observed_for_this_execution"
        return NOT, "candidate_admission_does_not_establish_a_covering_admission"

    def _absent(self, o):
        if not _holds(o, "mandatory_admission"):
            return NOT, "admission_requirement_not_defined"
        if not _holds(o, "window_finalized"):
            return NOT, "observation_window_open"
        if not _holds(o, "admission_coverage_complete"):
            return NOT, "admission_coverage_incomplete"
        return VIO, "mandatory_admission_absent_in_complete_bounded_history"


class TestedRouteEnforcement(Assessor):
    guards = (
        Guard("route_observation_accepted", "route_observation_unaccepted_or_missing"),
        Guard("same_protected_operation", "target_or_operation_not_bound"),
        Guard("outside_required_pep", "alternative_route_not_established"),
    )
    refusal_guards = (
        Guard("effect_window_complete", "no_effect_observation_not_complete"),
        Guard("valid_control_same_context", "valid_control_missing_or_incomparable"),
        Guard("required_boundary_refusal_accepted",
              "refusal_not_attributed_to_required_boundary"),
    )

    def decide(self, o):
        if _holds(o, "protected_effect_observed"):
            return VIO, "accepted_effect_observed_outside_required_pep"
        if _refuted(o, "protected_effect_observed"):
            for g in self.refusal_guards:
                if not g.passes(o):
                    return NOT, g.reason
            return EST, "named_route_refused_at_required_boundary_in_test_scope"
        return NOT, "protected_effect_unknown"


class PostconditionObserved(Assessor):
    guards = (
        Guard("readback_available", "readback_unavailable"),
        Guard("source_accepted", "readback_source_not_accepted"),
        Guard("same_target_and_predicate", "target_or_predicate_not_bound"),
        Guard("fresh_in_declared_window", "readback_stale_or_time_unbound"),
        Guard("settlement_reached", "declared_settlement_point_not_reached"),
    )

    def decide(self, o):
        if "expected_state" not in o or "observed_state" not in o:
            return NOT, "state_value_missing"
        if _json_equal(o["expected_state"], o["observed_state"]):
            return EST, "declared_postcondition_observed_at_named_point"
        return VIO, "declared_postcondition_disagreed_at_named_point"


def admission_accounting(o):
    return AdmissionAccounting().assess(o)


def tested_route_enforcement(o):
    return TestedRouteEnforcement().assess(o)


def postcondition_observed(o):
    return PostconditionObserved().assess(o)
