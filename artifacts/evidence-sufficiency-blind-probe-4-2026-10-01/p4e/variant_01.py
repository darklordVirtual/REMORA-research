"""Evidence-sufficiency assessors driven by a small rule DSL.

Each DSL line has the form

    <function>: <condition> => <status> <reason>

Rules for one function are tried top to bottom; the first rule whose
condition is true decides the verdict. Conditions use:

    holds NAME       key present and exactly JSON true
    refuted NAME     key present and exactly JSON false
    missing NAME     key absent
    equal NAME NAME  both values equal as JSON values
    always           true
    not X, X and Y, X or Y, ( X )   with precedence not > and > or
"""

RULES = """
admission_accounting: not (holds effect_source_accepted or holds effect_seen) => not_established execution_observation_unaccepted_or_missing
admission_accounting: not holds scope_accepted => not_established scope_unaccepted_or_missing
admission_accounting: holds admission_present and not holds admission_source_accepted => not_established admission_observation_unaccepted
admission_accounting: holds admission_present and holds admission_matches => established covering_admission_observed_for_this_execution
admission_accounting: holds admission_present => not_established candidate_admission_does_not_establish_a_covering_admission
admission_accounting: refuted admission_present and not holds mandatory_admission => not_established admission_requirement_not_defined
admission_accounting: refuted admission_present and not holds window_finalized => not_established observation_window_open
admission_accounting: refuted admission_present and not holds admission_coverage_complete => not_established admission_coverage_incomplete
admission_accounting: refuted admission_present => violated mandatory_admission_absent_in_complete_bounded_history
admission_accounting: always => not_established admission_presence_unknown

tested_route_enforcement: not holds route_observation_accepted => not_established route_observation_unaccepted_or_missing
tested_route_enforcement: not holds same_protected_operation => not_established target_or_operation_not_bound
tested_route_enforcement: not holds outside_required_pep => not_established alternative_route_not_established
tested_route_enforcement: not holds effect_observation_accepted => not_established protected_effect_observation_unaccepted
tested_route_enforcement: holds protected_effect_observed => violated accepted_effect_observed_outside_required_pep
tested_route_enforcement: refuted protected_effect_observed and not holds effect_window_complete => not_established no_effect_observation_not_complete
tested_route_enforcement: refuted protected_effect_observed and not holds valid_control_same_context => not_established valid_control_missing_or_incomparable
tested_route_enforcement: refuted protected_effect_observed and not holds required_boundary_refusal_accepted => not_established refusal_not_attributed_to_required_boundary
tested_route_enforcement: refuted protected_effect_observed => established named_route_refused_at_required_boundary_in_test_scope
tested_route_enforcement: always => not_established protected_effect_unknown

postcondition_observed: not holds readback_available => not_established readback_unavailable
postcondition_observed: not holds source_accepted => not_established readback_source_not_accepted
postcondition_observed: not holds same_target_and_predicate => not_established target_or_predicate_not_bound
postcondition_observed: not holds fresh_in_declared_window => not_established readback_stale_or_time_unbound
postcondition_observed: not holds settlement_reached => not_established declared_settlement_point_not_reached
postcondition_observed: missing expected_state or missing observed_state => not_established state_value_missing
postcondition_observed: equal expected_state observed_state => established declared_postcondition_observed_at_named_point
postcondition_observed: always => violated declared_postcondition_disagreed_at_named_point
"""

_STATUSES = ("established", "violated", "not_established")
_UNARY = ("holds", "refuted", "missing")
_KEYWORDS = ("not", "and", "or", "always", "equal") + _UNARY


def _tokenize(text):
    tokens = []
    for chunk in text.replace("(", " ( ").replace(")", " ) ").split():
        tokens.append(chunk)
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise SyntaxError("unexpected end of condition")
        self.pos += 1
        return tok

    def name(self):
        tok = self.take()
        if tok in _KEYWORDS or tok in ("(", ")"):
            raise SyntaxError("expected a key name, got %r" % tok)
        return tok

    def parse(self):
        node = self.parse_or()
        if self.peek() is not None:
            raise SyntaxError("trailing tokens: %r" % self.tokens[self.pos:])
        return node

    def parse_or(self):
        node = self.parse_and()
        while self.peek() == "or":
            self.take()
            node = ("or", node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_unary()
        while self.peek() == "and":
            self.take()
            node = ("and", node, self.parse_unary())
        return node

    def parse_unary(self):
        tok = self.take()
        if tok == "not":
            return ("not", self.parse_unary())
        if tok == "(":
            node = self.parse_or()
            if self.take() != ")":
                raise SyntaxError("expected ')'")
            return node
        if tok in _UNARY:
            return (tok, self.name())
        if tok == "equal":
            return ("equal", self.name(), self.name())
        if tok == "always":
            return ("always",)
        raise SyntaxError("unexpected token %r" % tok)


def _parse_rules(text):
    table = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        func, sep, rest = line.partition(":")
        if not sep:
            raise SyntaxError("missing ':' in rule %r" % line)
        cond_text, arrow, outcome = rest.partition("=>")
        if not arrow:
            raise SyntaxError("missing '=>' in rule %r" % line)
        parts = outcome.split()
        if len(parts) != 2 or parts[0] not in _STATUSES:
            raise SyntaxError("bad outcome in rule %r" % line)
        cond = _Parser(_tokenize(cond_text)).parse()
        table.setdefault(func.strip(), []).append((cond, parts[0], parts[1]))
    return table


def _json_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        return (isinstance(a, (int, float)) and isinstance(b, (int, float))
                and a == b)
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
            return False
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) or isinstance(b, dict):
        if not (isinstance(a, dict) and isinstance(b, dict)):
            return False
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_json_equal(a[k], b[k]) for k in a)
    return a == b


def _eval(node, o):
    op = node[0]
    if op == "always":
        return True
    if op == "not":
        return not _eval(node[1], o)
    if op == "and":
        return _eval(node[1], o) and _eval(node[2], o)
    if op == "or":
        return _eval(node[1], o) or _eval(node[2], o)
    if op == "holds":
        return node[1] in o and o[node[1]] is True
    if op == "refuted":
        return node[1] in o and o[node[1]] is False
    if op == "missing":
        return node[1] not in o
    if op == "equal":
        return _json_equal(o[node[1]], o[node[2]])
    raise ValueError("unknown node %r" % (op,))


_TABLE = _parse_rules(RULES)


def _run(func, o):
    for cond, status, reason in _TABLE[func]:
        if _eval(cond, o):
            return (status, reason)
    raise RuntimeError("no rule matched for %s" % func)


def admission_accounting(o):
    return _run("admission_accounting", o)


def tested_route_enforcement(o):
    return _run("tested_route_enforcement", o)


def postcondition_observed(o):
    return _run("postcondition_observed", o)
