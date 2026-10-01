"""Evidence-sufficiency assessors, table-driven implementation."""

ESTABLISHED = "established"
VIOLATED = "violated"
NOT_ESTABLISHED = "not_established"

_MISSING = object()


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
        return (isinstance(a, list) and isinstance(b, list)
                and len(a) == len(b)
                and all(_json_eq(x, y) for x, y in zip(a, b)))
    if isinstance(a, dict) or isinstance(b, dict):
        return (isinstance(a, dict) and isinstance(b, dict)
                and set(a.keys()) == set(b.keys())
                and all(_json_eq(a[k], b[k]) for k in a))
    return False


def _run(o, program):
    """Interpret a program: a list of steps.

    ("require", (keys...), reason)              all keys must hold
    ("branch", key, on_true, on_false, on_unknown)  three-way on a premise
    ("present", (keys...), reason)              keys must exist in o
    ("compare", a_key, b_key, eq_verdict, ne_verdict)
    ("verdict", status, reason)
    """
    for step in program:
        kind = step[0]
        if kind == "require":
            _, keys, reason = step
            if not all(_holds(o, k) for k in keys):
                return (NOT_ESTABLISHED, reason)
        elif kind == "branch":
            _, key, on_true, on_false, on_unknown = step
            if _holds(o, key):
                return _run(o, on_true)
            if _refuted(o, key):
                return _run(o, on_false)
            return _run(o, on_unknown)
        elif kind == "present":
            _, keys, reason = step
            if not all(k in o for k in keys):
                return (NOT_ESTABLISHED, reason)
        elif kind == "compare":
            _, ka, kb, eq_verdict, ne_verdict = step
            if _json_eq(o[ka], o[kb]):
                return eq_verdict
            return ne_verdict
        elif kind == "verdict":
            return (step[1], step[2])
        else:
            raise ValueError("unknown step kind: %r" % (kind,))
    raise ValueError("program fell through without a verdict")


# ---------------------------------------------------------------- admission

_ADMISSION_PRESENT = [
    ("branch", "admission_matches",
     [("require", ("admission_source_accepted",), "admission_observation_unaccepted"),
      ("verdict", ESTABLISHED, "covering_admission_observed_for_this_execution")],
     [("verdict", NOT_ESTABLISHED, "candidate_admission_does_not_establish_a_covering_admission")],
     [("verdict", NOT_ESTABLISHED, "candidate_admission_does_not_establish_a_covering_admission")]),
]

_ADMISSION_ABSENT = [
    ("require", ("mandatory_admission",), "admission_requirement_not_defined"),
    ("require", ("window_finalized",), "observation_window_open"),
    ("require", ("admission_coverage_complete",), "admission_coverage_incomplete"),
    ("verdict", VIOLATED, "mandatory_admission_absent_in_complete_bounded_history"),
]

_ADMISSION_UNKNOWN = [
    ("verdict", NOT_ESTABLISHED, "admission_presence_unknown"),
]

ADMISSION_PROGRAM = [
    ("require", ("effect_source_accepted", "effect_seen"), "execution_observation_unaccepted_or_missing"),
    ("require", ("scope_accepted",), "scope_unaccepted_or_missing"),
    ("branch", "admission_present", _ADMISSION_PRESENT, _ADMISSION_ABSENT, _ADMISSION_UNKNOWN),
]


def admission_accounting(o):
    return _run(o, ADMISSION_PROGRAM)


# -------------------------------------------------------------------- route

_ROUTE_EFFECT = [
    ("verdict", VIOLATED, "accepted_effect_observed_outside_required_pep"),
]

_ROUTE_NO_EFFECT = [
    ("require", ("effect_window_complete",), "no_effect_observation_not_complete"),
    ("require", ("valid_control_same_context",), "valid_control_missing_or_incomparable"),
    ("require", ("required_boundary_refusal_accepted",), "refusal_not_attributed_to_required_boundary"),
    ("verdict", ESTABLISHED, "named_route_refused_at_required_boundary_in_test_scope"),
]

_ROUTE_UNKNOWN = [
    ("verdict", NOT_ESTABLISHED, "protected_effect_unknown"),
]

ROUTE_PROGRAM = [
    ("require", ("route_observation_accepted",), "route_observation_unaccepted_or_missing"),
    ("require", ("same_protected_operation",), "target_or_operation_not_bound"),
    ("require", ("outside_required_pep",), "alternative_route_not_established"),
    ("require", ("effect_observation_accepted",), "protected_effect_observation_unaccepted"),
    ("branch", "protected_effect_observed", _ROUTE_EFFECT, _ROUTE_NO_EFFECT, _ROUTE_UNKNOWN),
]


def tested_route_enforcement(o):
    return _run(o, ROUTE_PROGRAM)


# ------------------------------------------------------------ postcondition

POSTCONDITION_PROGRAM = [
    ("require", ("readback_available",), "readback_unavailable"),
    ("require", ("source_accepted",), "readback_source_not_accepted"),
    ("require", ("same_target_and_predicate",), "target_or_predicate_not_bound"),
    ("require", ("fresh_in_declared_window",), "readback_stale_or_time_unbound"),
    ("require", ("settlement_reached",), "declared_settlement_point_not_reached"),
    ("present", ("expected_state", "observed_state"), "state_value_missing"),
    ("compare", "expected_state", "observed_state",
     (ESTABLISHED, "declared_postcondition_observed_at_named_point"),
     (VIOLATED, "declared_postcondition_disagreed_at_named_point")),
]


def postcondition_observed(o):
    return _run(o, POSTCONDITION_PROGRAM)
