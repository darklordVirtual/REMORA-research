"""Evidence-sufficiency assessors, written as a small step interpreter.

Each assessor is a table of named states. A state is one of:
  ("require", key_or_keys, next_state, reason)  -> all premises must hold, else not_established
  ("branch", key, state_if_holds, state_if_refuted, state_if_unknown)
  ("present", keys, next_state, reason)         -> all keys must be present, else not_established
  ("compare", key_a, key_b, ok_reason, bad_reason)
  ("emit", status, reason)
Execution starts at state "start" and runs until an emit/compare terminates.
"""

NE = "not_established"
EST = "established"
VIO = "violated"


def _holds(o, key):
    if key not in o:
        return False
    v = o[key]
    return isinstance(v, bool) and v is True


def _refuted(o, key):
    if key not in o:
        return False
    v = o[key]
    return isinstance(v, bool) and v is False


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _json_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if a is None or b is None:
        return a is None and b is None
    if _is_number(a) or _is_number(b):
        return _is_number(a) and _is_number(b) and a == b
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
            return False
        if len(a) != len(b):
            return False
        for x, y in zip(a, b):
            if not _json_equal(x, y):
                return False
        return True
    if isinstance(a, dict) or isinstance(b, dict):
        if not (isinstance(a, dict) and isinstance(b, dict)):
            return False
        if set(a.keys()) != set(b.keys()):
            return False
        for k in a:
            if not _json_equal(a[k], b[k]):
                return False
        return True
    return type(a) is type(b) and a == b


def _run(machine, o):
    if not isinstance(o, dict):
        o = {}
    state = "start"
    for _ in range(1000):
        step = machine[state]
        kind = step[0]
        if kind == "require":
            _, keys, nxt, reason = step
            if isinstance(keys, str):
                keys = (keys,)
            if all(_holds(o, k) for k in keys):
                state = nxt
            else:
                return (NE, reason)
        elif kind == "branch":
            _, key, on_hold, on_refute, on_unknown = step
            if _holds(o, key):
                state = on_hold
            elif _refuted(o, key):
                state = on_refute
            else:
                state = on_unknown
        elif kind == "present":
            _, keys, nxt, reason = step
            if all(k in o for k in keys):
                state = nxt
            else:
                return (NE, reason)
        elif kind == "compare":
            _, ka, kb, ok_reason, bad_reason = step
            if _json_equal(o[ka], o[kb]):
                return (EST, ok_reason)
            return (VIO, bad_reason)
        elif kind == "emit":
            return (step[1], step[2])
        else:  # pragma: no cover
            raise RuntimeError("bad state kind %r" % kind)
    raise RuntimeError("machine did not terminate")


_ADMISSION = {
    "start": ("require", ("effect_source_accepted", "effect_seen"), "scope",
              "execution_observation_unaccepted_or_missing"),
    "scope": ("require", "scope_accepted", "presence", "scope_unaccepted_or_missing"),
    "presence": ("branch", "admission_present", "cand_source", "closed_mandatory", "closed_mandatory"),
    "cand_source": ("require", "admission_source_accepted", "cand_match",
                    "admission_observation_unaccepted"),
    "cand_match": ("branch", "admission_matches", "covered", "not_covering", "not_covering"),
    "covered": ("emit", EST, "covering_admission_observed_for_this_execution"),
    "not_covering": ("emit", NE, "candidate_admission_does_not_establish_a_covering_admission"),
    "closed_mandatory": ("require", "mandatory_admission", "closed_window",
                         "admission_requirement_not_defined"),
    "closed_window": ("require", "window_finalized", "closed_coverage", "observation_window_open"),
    "closed_coverage": ("require", "admission_coverage_complete", "absent",
                        "admission_coverage_incomplete"),
    "absent": ("emit", VIO, "mandatory_admission_absent_in_complete_bounded_history"),
    "unknown": ("emit", NE, "admission_presence_unknown"),
}

_ROUTE = {
    "start": ("require", "route_observation_accepted", "bound",
              "route_observation_unaccepted_or_missing"),
    "bound": ("require", "same_protected_operation", "outside", "target_or_operation_not_bound"),
    "outside": ("require", "outside_required_pep", "effect_obs",
                "alternative_route_not_established"),
    "effect_obs": ("require", "effect_observation_accepted", "effect",
                   "protected_effect_observation_unaccepted"),
    "effect": ("branch", "protected_effect_observed", "leak", "no_effect_window", "effect_unknown"),
    "leak": ("emit", VIO, "accepted_effect_observed_outside_required_pep"),
    "no_effect_window": ("require", "effect_window_complete", "control",
                         "no_effect_observation_not_complete"),
    "control": ("require", "valid_control_same_context", "refusal",
                "valid_control_missing_or_incomparable"),
    "refusal": ("require", "required_boundary_refusal_accepted", "refused",
                "refusal_not_attributed_to_required_boundary"),
    "refused": ("emit", EST, "named_route_refused_at_required_boundary_in_test_scope"),
    "effect_unknown": ("emit", NE, "protected_effect_unknown"),
}

_POSTCONDITION = {
    "start": ("require", "readback_available", "source", "readback_unavailable"),
    "source": ("require", "source_accepted", "bound", "readback_source_not_accepted"),
    "bound": ("require", "same_target_and_predicate", "fresh", "target_or_predicate_not_bound"),
    "fresh": ("require", "fresh_in_declared_window", "settled", "readback_stale_or_time_unbound"),
    "settled": ("require", "settlement_reached", "values", "declared_settlement_point_not_reached"),
    "values": ("present", ("expected_state", "observed_state"), "compare", "state_value_missing"),
    "compare": ("compare", "expected_state", "observed_state",
                "declared_postcondition_observed_at_named_point",
                "declared_postcondition_disagreed_at_named_point"),
}


def admission_accounting(o):
    return _run(_ADMISSION, o)


def tested_route_enforcement(o):
    return _run(_ROUTE, o)


def postcondition_observed(o):
    return _run(_POSTCONDITION, o)
