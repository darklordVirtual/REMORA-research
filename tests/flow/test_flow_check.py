# SPDX-License-Identifier: BUSL-1.1
"""IFC-05a: recipients and the flow check (SDD v1.3 §3.5, §3.6(d)).

The four invariant tests the SDD makes mandatory for IFC-05 are here, at the
level of the check itself:

- a TRUSTED parameter handle satisfies ``integrity_required`` after the model
  read untrusted content (``test_trusted_parameter_survives_untrusted_context``);
- the same value retyped as a literal does not
  (``test_literal_after_untrusted_read_is_untrusted``);
- a parameter in a field that does not accept its role is refused
  (``test_parameter_role_binding``);
- the payload label includes ``L_ctx`` when only handles are passed
  (``test_payload_confidentiality_includes_context``).

Wiring the verdict into the decision engine (rungs F1 to F6) is IFC-05b.
"""
from __future__ import annotations

import pytest

from remora.flow.check import FlowVerdict, flow_check, recipients
from remora.flow.handles import HandleRecord, HandleStore, InMemoryHandleBackend, handle_token
from remora.flow.label import BOTTOM, PUBLIC, Integrity, Label, join
from remora.flow.spec import parse_flow

USER = "user://acme/alice"
MODEL = "ext://api.provider.example"
BOB = "email://corp.example/bob"
EVE = "email://evil.example/eve"

SEND_EMAIL = parse_flow({
    "provider": "ext://mail.corp.example",
    "arguments": {"to": {"kind": "email"}, "cc": {"kind": "email"},
                  "subject": {"kind": "text"}, "body": {"kind": "text"}},
    "sources": {"default_integrity": "TRUSTED"},
    "sink": {"recipients": {"from_args": {"to": "email", "cc": "email"}},
             "payload_args": ["subject", "body"],
             "integrity_required": ["to", "cc"],
             "roles_accepted": {"to": ["recipient"], "cc": ["recipient"]}},
})
GET_WEBPAGE = parse_flow({
    "provider": "tcb", "arguments": {"url": {"kind": "url"}},
    "sources": {"fields": [{"path": "$", "readers": "PUBLIC", "public_justification": "t",
                            "return_mode": "BY_VALUE"}]},
    "sink": {"recipients": {"url_host_of": "url"}, "payload_args": ["url"]},
})
DELETE_ALL = parse_flow({
    "provider": "tcb", "arguments": {"scope": {"kind": "text"}}, "sources": {},
    "sink": {"recipients": {"static": [USER]}, "control_integrity_required": True},
})

CLEAN_CTX = Label({USER, MODEL, BOB, "email://corp.example/*"}, Integrity.TRUSTED)
TAINTED_CTX = Label({USER, MODEL, BOB}, Integrity.UNTRUSTED)
SECRET = Label({USER, MODEL}, Integrity.TRUSTED)          # the user's own data
PARAM = Label({USER, MODEL, BOB}, Integrity.TRUSTED)     # a task parameter handle


def _check(flow=SEND_EMAIL, ctx=CLEAN_CTX, args=None, labels=None, **kw):
    args = args if args is not None else {"to": "bob@corp.example", "subject": "hi",
                                          "body": "hello"}
    labels = labels if labels is not None else {k: ctx for k in args}
    return flow_check(flow, context_label=ctx, value_labels=labels, resolved_args=args,
                      epoch=3, **kw)


# ── recipients ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("flow, args, expected", [
    (SEND_EMAIL, {"to": "bob@corp.example", "cc": ["carol@corp.example"]},
     {BOB, "email://corp.example/carol", "ext://mail.corp.example"}),
    (SEND_EMAIL, {"to": "bob@corp.example", "cc": None}, {BOB, "ext://mail.corp.example"}),
    (GET_WEBPAGE, {"url": "https://Evil.Example:8443/x?q=1"}, {"ext://evil.example"}),
    (DELETE_ALL, {"scope": "all"}, {USER}),
])
def test_recipients_are_computed_from_the_resolved_call(flow, args, expected):
    resolved, unresolved = recipients(flow, args)
    assert resolved == frozenset(expected) and unresolved == ()


def test_iban_and_resource_recipients():
    pay = parse_flow({"provider": "tcb", "arguments": {"iban": {"kind": "iban"}},
                      "sources": {}, "sink": {"recipients": {"iban_of": "iban"}}})
    assert recipients(pay, {"iban": "no93 8601 1117 947"})[0] == {"iban://no9386011117947"}
    write = parse_flow({"provider": "tcb", "arguments": {"path": {"kind": "resource"}},
                        "sources": {}, "sink": {"recipients": {"resource_of": "path"}}})
    acl = {"res://files/q3": [BOB, USER]}
    assert recipients(write, {"path": "res://files/q3"},
                      resource_acl=lambda r: acl.get(r, []))[0] == {BOB, USER}


@pytest.mark.parametrize("flow, args", [
    (SEND_EMAIL, {"to": "Bob <bob@corp.example>"}),
    (SEND_EMAIL, {"to": "not-an-address"}),
    (SEND_EMAIL, {"to": 7}),
    (GET_WEBPAGE, {"url": "javascript:alert(1)"}),
    (GET_WEBPAGE, {"url": "https://user@corp.example/"}),
    (GET_WEBPAGE, {"url": "https://bücher.example/"}),
    (parse_flow({"provider": "tcb", "arguments": {"iban": {"kind": "iban"}}, "sources": {},
                 "sink": {"recipients": {"iban_of": "iban"}}}), {"iban": "not an iban"}),
    (parse_flow({"provider": "tcb", "arguments": {"path": {"kind": "resource"}},
                 "sources": {}, "sink": {"recipients": {"resource_of": "path"}}}),
     {"path": "res://files/q3"}),  # no ACL resolver
])
def test_a_recipient_that_cannot_be_resolved_is_named_unresolved(flow, args):
    _, unresolved = recipients(flow, args)
    assert unresolved, args
    verdict = flow_check(flow, context_label=BOTTOM, value_labels={}, resolved_args=args,
                         epoch=0)
    # An unresolvable recipient can never be shown to be a reader.
    assert verdict.conf_viol


SEND_IN_TCB = parse_flow({
    "provider": "tcb",
    "arguments": {"to": {"kind": "email"}, "body": {"kind": "text"}},
    "sources": {},
    "sink": {"recipients": {"from_args": {"to": "email"}}, "payload_args": ["body"]},
})
FETCH = parse_flow({"provider": "tcb", "arguments": {"url": {"kind": "url"}}, "sources": {},
                    "sink": {"recipients": {"url_host_of": "url"}}})
PAY = parse_flow({"provider": "tcb", "arguments": {"iban": {"kind": "iban"}}, "sources": {},
                  "sink": {"recipients": {"iban_of": "iban"}}})
WRITE = parse_flow({"provider": "tcb", "arguments": {"path": {"kind": "resource"}},
                    "sources": {}, "sink": {"recipients": {"resource_of": "path"}}})


@pytest.mark.parametrize("flow, argument", [
    (SEND_IN_TCB, "to"), (FETCH, "url"), (PAY, "iban"), (WRITE, "path")])
@pytest.mark.parametrize("value", [[], (), None, "omitted"])
def test_a_derived_recipient_rule_that_yields_no_one_is_unresolved(flow, argument, value):
    """RMR-AUD-007: an empty, null or missing recipient argument reached no
    one, so a secret payload passed as clean. The tool decides where such a
    call goes, so no reader set can be shown to contain the recipient."""
    secret = Label({USER}, Integrity.TRUSTED)
    args = {"body": "TOP_SECRET"}
    if value != "omitted":
        args[argument] = value
    verdict = flow_check(flow, context_label=secret, value_labels={"body": secret},
                         resolved_args=args, epoch=1,
                         resource_acl=lambda r: [USER])
    assert f"unresolved:{argument}" in verdict.conf_viol
    assert not verdict.clean


def test_an_absent_cc_beside_a_resolved_to_is_not_unresolved():
    """The rule as a whole must name someone; each optional argument need not."""
    resolved, unresolved = recipients(SEND_EMAIL, {"to": "bob@corp.example", "cc": []})
    assert resolved == {BOB, "ext://mail.corp.example"} and unresolved == ()


def test_a_rule_with_no_values_names_every_argument_unresolved():
    _, unresolved = recipients(SEND_EMAIL, {"to": None, "cc": []})
    assert set(unresolved) == {"to", "cc"}


# ── confidentiality ───────────────────────────────────────────────────────

def test_a_clean_call_has_no_violations():
    verdict = _check(ctx=Label({USER, MODEL, BOB, "ext://mail.corp.example"},
                               Integrity.TRUSTED))
    assert verdict.clean and verdict.epoch == 3


def test_the_provider_is_an_implicit_recipient():
    verdict = _check()  # the context does not admit ext://mail.corp.example
    assert verdict.conf_viol == frozenset({"ext://mail.corp.example"})


def test_payload_confidentiality_includes_context():
    """Only handles are passed, but the model chose them after reading the secret."""
    ctx = Label({USER, MODEL}, Integrity.TRUSTED)
    verdict = _check(ctx=ctx, args={"to": "bob@corp.example", "subject": "s", "body": "b"},
                     labels={"to": PARAM, "subject": BOTTOM, "body": BOTTOM})
    assert BOB in verdict.conf_viol
    assert verdict.payload_label == ctx


def test_a_declassified_recipient_is_not_a_violation():
    verdict = _check(ctx=SECRET, declassified=frozenset({BOB, "ext://mail.corp.example"}))
    assert not verdict.conf_viol


def test_only_payload_fields_count_toward_the_payload_label():
    ctx = Label({USER, MODEL, BOB, "ext://mail.corp.example"}, Integrity.TRUSTED)
    verdict = _check(ctx=ctx, args={"to": "bob@corp.example", "subject": "s", "body": "b"},
                     labels={"to": Label({USER}, Integrity.TRUSTED), "subject": ctx,
                             "body": ctx})
    assert not verdict.conf_viol


def test_without_payload_args_every_argument_is_payload():
    flow = parse_flow({"provider": "tcb", "arguments": {"q": {"kind": "text"},
                                                        "url": {"kind": "url"}},
                       "sources": {}, "sink": {"recipients": {"url_host_of": "url"}}})
    verdict = flow_check(flow, context_label=BOTTOM,
                         value_labels={"q": SECRET, "url": BOTTOM},
                         resolved_args={"q": "secret", "url": "https://evil.example/"},
                         epoch=0)
    assert verdict.conf_viol == frozenset({"ext://evil.example"})


def test_a_field_without_a_value_label_counts_as_literal_text():
    verdict = _check(ctx=SECRET, labels={})
    assert BOB in verdict.conf_viol and verdict.payload_label == SECRET


# ── integrity ─────────────────────────────────────────────────────────────

def _resolved(ctx, to_value, store):
    res = store.resolve("acme", ("ctx_a",), {"to": to_value, "subject": "s", "body": "b"},
                        context_label=ctx)
    return res.args, res.value_labels


def _param_store():
    store = HandleStore(InMemoryHandleBackend(), clock=lambda: 0.0)
    store.put_all([HandleRecord(handle_id="P" * 16, tenant_id="acme", context_id="ctx_a",
                                value="bob@corp.example", label=PARAM, type_tag="string",
                                created_by_proposal="turn-1", expires_at=10.0)])
    return store


def test_trusted_parameter_survives_untrusted_context():
    args, labels = _resolved(TAINTED_CTX, handle_token("P" * 16), _param_store())
    verdict = _check(ctx=TAINTED_CTX, args=args, labels=labels,
                     parameter_roles={"to": "recipient"})
    assert not verdict.int_viol


def test_literal_after_untrusted_read_is_untrusted():
    args, labels = _resolved(TAINTED_CTX, "bob@corp.example", _param_store())
    verdict = _check(ctx=TAINTED_CTX, args=args, labels=labels)
    assert verdict.int_viol == frozenset({"to"})


def test_parameter_role_binding():
    args, labels = _resolved(TAINTED_CTX, handle_token("P" * 16), _param_store())
    verdict = _check(ctx=TAINTED_CTX, args=args, labels=labels,
                     parameter_roles={"to": "amount"})
    assert verdict.int_viol == frozenset({"to"})


def test_a_parameter_in_a_field_with_no_declared_roles_is_refused():
    flow = parse_flow({"provider": "tcb", "arguments": {"iban": {"kind": "iban"}},
                       "sources": {}, "sink": {"recipients": {"iban_of": "iban"},
                                               "integrity_required": ["iban"]}})
    verdict = flow_check(flow, context_label=CLEAN_CTX, value_labels={"iban": PARAM},
                         resolved_args={"iban": "NO9386011117947"}, epoch=0,
                         parameter_roles={"iban": "payee"})
    assert verdict.int_viol == frozenset({"iban"})


def test_endorsement_and_grants_clear_integrity_violations():
    args = {"to": "bob@corp.example", "subject": "s", "body": "b"}
    labels = {k: TAINTED_CTX for k in args}
    assert _check(ctx=TAINTED_CTX, args=args, labels=labels).int_viol == {"to"}
    endorsed = _check(ctx=TAINTED_CTX, args=args, labels=labels,
                      endorsed=lambda field, value: (field, value) == ("to", "bob@corp.example"))
    assert not endorsed.int_viol
    granted = _check(ctx=TAINTED_CTX, args=args, labels=labels,
                     integrity_granted=frozenset({"to"}))
    assert not granted.int_viol


def test_an_absent_optional_field_needs_no_integrity():
    verdict = _check(ctx=TAINTED_CTX, args={"to": handle_token("P" * 16)},
                     labels={"to": PARAM}, parameter_roles={"to": "recipient"})
    assert "cc" not in verdict.int_viol


def test_control_integrity():
    assert _check(flow=DELETE_ALL, ctx=TAINTED_CTX, args={"scope": "all"}).ctrl_viol
    assert not _check(flow=DELETE_ALL, ctx=CLEAN_CTX, args={"scope": "all"}).ctrl_viol
    assert not _check(flow=DELETE_ALL, ctx=TAINTED_CTX, args={"scope": "all"},
                      control_granted=True).ctrl_viol
    # A tool that does not ask for it never has a control violation.
    assert not _check(ctx=TAINTED_CTX).ctrl_viol


# ── the digest ────────────────────────────────────────────────────────────

def test_the_digest_binds_violations_and_the_payload_label():
    a = _check(ctx=SECRET)
    assert a.digest == _check(ctx=SECRET).digest
    assert len(a.digest) == 64
    # New data joining the payload changes the digest even when the same
    # violations fire (a grant bound to the old digest must stop applying).
    b = _check(ctx=SECRET, labels={"to": SECRET, "subject": SECRET,
                                   "body": Label({USER, MODEL}, Integrity.UNTRUSTED)})
    assert b.conf_viol == a.conf_viol and b.digest != a.digest
    c = _check(ctx=SECRET, declassified=frozenset({BOB}))
    assert c.digest != a.digest
    # The epoch is not in the digest: an unrelated raise does not invalidate it.
    assert flow_check(SEND_EMAIL, context_label=SECRET, value_labels={},
                      resolved_args={"to": "bob@corp.example", "subject": "s", "body": "b"},
                      epoch=99).digest == _check(ctx=SECRET, labels={}).digest


def test_the_verdict_is_frozen_and_complete():
    verdict = _check(ctx=SECRET)
    assert isinstance(verdict, FlowVerdict)
    with pytest.raises(AttributeError):
        verdict.epoch = 4  # type: ignore[misc]
    assert not verdict.clean
    assert verdict.payload_label == join(SECRET, SECRET)
    assert PUBLIC is not verdict.payload_label.readers


# ── cases found by mutation testing ───────────────────────────────────────

@pytest.mark.parametrize("value", ["@corp.example", "bob@", "a@b@c.example"])
def test_half_an_address_is_unresolved_and_named(value):
    assert recipients(SEND_EMAIL, {"to": value}) == (
        frozenset({"ext://mail.corp.example"}), ("to",))


def test_plain_http_resolves_and_other_schemes_do_not():
    assert recipients(GET_WEBPAGE, {"url": "http://corp.example/a"})[0] == {
        "ext://corp.example"}
    for url in ("ftp://corp.example/a", "file:///etc/passwd", "https://"):
        assert recipients(GET_WEBPAGE, {"url": url})[1] == ("url",), url


def test_principal_recipients_are_canonical_resources():
    flow = parse_flow({"provider": "tcb", "arguments": {"who": {"kind": "principal"}},
                       "sources": {}, "sink": {"recipients": {"from_args": {"who": "principal"}}}})
    assert recipients(flow, {"who": "USER://Acme/bob"}) == (
        frozenset({"user://acme/bob"}), ())
    assert recipients(flow, {"who": "bob@corp.example"})[1] == ("who",)


def test_the_resource_acl_resolver_reaches_the_check():
    write = parse_flow({"provider": "tcb", "arguments": {"path": {"kind": "resource"},
                                                         "body": {"kind": "text"}},
                        "sources": {}, "sink": {"recipients": {"resource_of": "path"}}})
    verdict = flow_check(write, context_label=SECRET, value_labels={},
                         resolved_args={"path": "res://files/q3", "body": "x"}, epoch=0,
                         resource_acl=lambda r: [BOB])
    assert verdict.conf_viol == frozenset({BOB})


def test_every_integrity_field_is_checked_after_an_absent_one():
    verdict = _check(ctx=TAINTED_CTX, args={"cc": "carol@corp.example"},
                     labels={"cc": TAINTED_CTX})
    assert verdict.int_viol == frozenset({"cc"})


def test_the_digest_format():
    """The digest is part of the lease contract (§3.8): pin its preimage."""
    import hashlib
    import json

    from remora.flow.label import canonical_bytes

    for verdict in (_check(ctx=SECRET), _check(flow=DELETE_ALL, ctx=TAINTED_CTX,
                                               args={"scope": "all"})):
        body = json.dumps({"conf": sorted(verdict.conf_viol), "int": sorted(verdict.int_viol),
                           "ctrl": verdict.ctrl_viol}, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        expected = hashlib.sha256(b"REMORA/FLOW-VERDICT/v1\x00" + body + b"\x00"
                                  + canonical_bytes(verdict.payload_label)).hexdigest()
        assert verdict.digest == expected
    assert _check(flow=DELETE_ALL, ctx=TAINTED_CTX, args={"scope": "all"}).ctrl_viol


# ── a world-readable resource (resource ACL registry, 2026-11-10) ──────────

_WRITE = {"provider": "tcb", "arguments": {"path": {"kind": "resource"},
                                           "body": {"kind": "text"}},
          "sources": {}, "sink": {"recipients": {"resource_of": "path"}}}


def test_a_write_to_a_world_readable_resource_takes_only_public_data():
    """An ACL that answers PUBLIC names everyone. Restricted data may not go
    there, and public data may: the check no longer needs a list of everyone."""
    from remora.flow.check import PUBLIC_RECIPIENT

    write = parse_flow(_WRITE)
    args = {"path": "res://records/pub-1", "body": "x"}
    assert recipients(write, args, resource_acl=lambda r: PUBLIC) == (
        frozenset({PUBLIC_RECIPIENT}), ())
    secret = flow_check(write, context_label=SECRET, value_labels={}, resolved_args=args,
                        epoch=0, resource_acl=lambda r: PUBLIC)
    assert secret.conf_viol == frozenset({PUBLIC_RECIPIENT})
    public = flow_check(write, context_label=BOTTOM, value_labels={}, resolved_args=args,
                        epoch=0, resource_acl=lambda r: PUBLIC)
    assert public.clean


def test_the_public_recipient_is_within_no_reader_set_however_it_is_written():
    from remora.flow.check import PUBLIC_RECIPIENT
    from remora.flow.label import flows_to

    assert flows_to(BOTTOM, PUBLIC_RECIPIENT)
    for readers in ({USER}, {"public://anyone"}, {"public://anyone/*"}, {USER, BOB, MODEL}):
        assert not flows_to(Label(readers, Integrity.TRUSTED), PUBLIC_RECIPIENT), readers


def test_a_resource_the_acl_names_no_reader_for_is_unresolved_not_open():
    """Fail closed. A registry that answers with no reader for a resource
    (an unknown one, typically) has not said nobody receives the write, and
    the check must not read it as 'no recipient the data may not reach'."""
    write = parse_flow(_WRITE)
    args = {"path": "res://records/unknown", "body": "x"}
    assert recipients(write, args, resource_acl=lambda r: []) == (frozenset(), ("path",))
    for label in (BOTTOM, SECRET):
        verdict = flow_check(write, context_label=label, value_labels={}, resolved_args=args,
                             epoch=0, resource_acl=lambda r: [])
        assert verdict.conf_viol == frozenset({"unresolved:path"})


@pytest.mark.parametrize("answer", [None, 7, "user://acme/alice", [7], ["not a principal"],
                                    {"user://acme/alice": True}])
def test_a_registry_answer_that_is_not_a_list_of_principals_is_unresolved(answer):
    write = parse_flow(_WRITE)
    args = {"path": "res://records/pub-1", "body": "x"}
    found, unresolved = recipients(write, args, resource_acl=lambda r: answer)
    assert found == frozenset() and unresolved == ("path",), answer


def test_a_registry_that_raises_is_unresolved_not_a_crash():
    write = parse_flow(_WRITE)

    def broken(resource):
        raise RuntimeError("registry down")

    assert recipients(write, {"path": "res://records/pub-1"}, resource_acl=broken) == (
        frozenset(), ("path",))


def test_the_registry_is_asked_about_the_canonical_resource():
    write = parse_flow(_WRITE)
    asked = []

    def acl(resource):
        asked.append(resource)
        return [USER]

    recipients(write, {"path": "RES://Records/pub-1/"}, resource_acl=acl)
    assert asked == ["res://records/pub-1"]
