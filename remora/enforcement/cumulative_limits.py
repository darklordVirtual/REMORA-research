# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Cumulative limits on governed tool calls, reserved before dispatch.

A per-call check sees one call. It cannot see that three payments of 7000
pass a budget of 20000, that ten setpoint moves of 0.5 degC add up to 5 degC,
or that a fan was started eight times in an hour. This module measures every
call that consumes something and refuses the one that would take a running
total past its declared limit, before the call reaches the tool.

A deployment declares, in a ``remora-cumulative-limits/v1`` policy:

``meters``
    Per tool, what one call consumes. A meter has a ``quantity`` name and a
    kind. ``sum`` takes an amount from an argument (a payment, minutes of
    runtime, a volume). ``count`` charges a fixed amount per call (one start,
    one actuation). ``change`` charges how far an absolute value moves from
    the last value REMORA let through for the same resource (a setpoint, a
    valve position), so a large move cannot be split into small ones. A
    meter may name the argument that identifies the resource (``AHU-1``) and
    the unit, either fixed or from an argument.
``limits``
    Per tenant and quantity, a ``max`` in the meter's unit, optionally per
    sliding window of ``window_seconds``. A limit is for one principal or
    ``"*"`` (shared by every principal, so two agents cannot each spend it),
    and for one resource, ``"*"`` (each resource separately) or no resource
    (all resources together). A call must fit every limit that matches it.
``baselines``
    For ``change`` meters, the value each resource starts from. A change
    meter with no known value refuses; nothing is guessed.
``coverage``
    ``listed`` governs only metered tools. ``all_writes`` also refuses any
    tool whose signed ToolSpec is not a read and that has no meter, so a
    write tool added later cannot run unbounded by being forgotten.
``idempotency``
    Per tool, the ``key_arguments`` that identify one operation (for a
    payment: payee, amount, unit and the payer's reference). A second call
    with the same key is the same operation, not a second one: it refuses
    while the first is in flight (``limit_duplicate_in_flight``), after it
    ran (``limit_duplicate_operation``) and while its outcome is unknown
    (``limit_outcome_unknown``). It may run only once the first provably did
    not. Neither the charge nor the effect happens twice. Without a declared
    key, two calls are two operations, as before; a guard built with
    ``require_keys`` refuses a metered write tool that declares none
    (``limit_key_undeclared``), so a payment that cannot be identified cannot
    be charged twice either.
``non_execution``
    Per tool, the ``trusted_sources`` whose statement that a call did not run
    the authority accepts. A tool adapter raises ``ToolDidNotExecute(source,
    detail)`` when its rail refused or was never reached. Only a statement
    from a declared source returns the reservation at once; from any other
    source the call is held as unknown, like a call that raised anything
    else, until a reviewer resolves it. The authority that signs the budget
    thereby also says whose word may free it.

Numbers are exact: a value is scaled by the meter's ``scale`` and must then
be an integer, so a move too small to count is refused rather than rounded
to nothing. Negative amounts are refused, so nothing can be paid back into
a limit by a call.

What this guarantees: the sum of reservations inside a window never passes
the limit, because every reservation is one serialized ledger transaction
(``BEGIN IMMEDIATE`` on a host's SQLite file; one advisory lock on a
Postgres database that every executor shares). A reservation is
returned only when the call provably did not run:

- the fence refused before the write;
- the tool raised ``ToolDidNotExecute`` from a source the policy trusts for
  that tool (the rail refused or was never reached);
- the lease expired before the tool was started (``begin`` and that release
  are serialized, so a released reservation never starts);
- a reviewer other than the proposer resolved an unknown outcome as not
  executed (``resolve``), and the deployment's evidence checker confirmed
  the reviewer's statement against the rail or plant.

A call whose outcome is unknown keeps its reservation until it is resolved;
it is never released on a timer, and never on a reviewer's word alone: a
guard without an evidence checker refuses every resolution
(``limit_evidence_unchecked``), so the budget stays held. A ``change`` meter's last value is the value REMORA last let
through; a call that fails or whose outcome is unknown leaves the resource
``unknown``, and the next change refuses until a baseline with a new
``seed_id`` is declared or the outcome is resolved. Hosts share a limit only
when they share the Postgres ledger; separate SQLite files are separate
limits. The ledger does not observe the plant or the payment rail.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

SCHEMA = "remora-cumulative-limits/v1"
MAX_UNITS = 10**12  # bound on any scaled amount, limit or baseline

#: Refusal reasons, as they appear in dispatch results and audit records.
AMOUNT_INVALID = "limit_amount_invalid"
UNIT_INVALID = "limit_unit_invalid"
RESOURCE_INVALID = "limit_resource_invalid"
PRINCIPAL_MISSING = "limit_principal_missing"
PRINCIPAL_INVALID = "limit_principal_invalid"
UNDECLARED = "limit_undeclared"
TOOL_UNMETERED = "limit_tool_unmetered"
COVERAGE_UNKNOWN = "limit_coverage_unknown"
EXCEEDED = "limit_exceeded"
BASELINE_UNKNOWN = "limit_baseline_unknown"
RESOURCE_BUSY = "limit_resource_busy"
CHANGED = "limit_changed"
LEDGER_UNAVAILABLE = "limit_ledger_unavailable"
OBSERVATION_UNAVAILABLE = "limit_observation_unavailable"
STATE_CHANGED = "limit_state_changed"
INVOCATION_DIFFERS = "limit_invocation_differs"
POLICY_CHANGED = "limit_policy_changed"
DUPLICATE_IN_FLIGHT = "limit_duplicate_in_flight"
DUPLICATE = "limit_duplicate_operation"
OUTCOME_UNKNOWN = "limit_outcome_unknown"
IDEMPOTENCY_KEY_INVALID = "limit_idempotency_key_invalid"
RESERVATION_RELEASED = "limit_reservation_released"
NOT_FOUND = "limit_operation_not_found"
NOT_UNKNOWN = "limit_operation_not_unknown"
RESOLVER_IS_PRINCIPAL = "limit_resolver_is_principal"
KEY_UNDECLARED = "limit_key_undeclared"
EVIDENCE_UNCHECKED = "limit_evidence_unchecked"
EVIDENCE_UNAVAILABLE = "limit_evidence_unavailable"
EVIDENCE_DISPUTED = "limit_evidence_disputed"

KINDS = ("sum", "count", "change")
#: Joins the parts of ledger keys; refused inside any part.
_SEP = "\x1f"
COVERAGES = ("listed", "all_writes")


SIGNED_SCHEMA = "remora-cumulative-limits-signed/v1"


class LimitPolicyError(ValueError):
    """The declared policy is malformed; the deployment must not start."""


def canonical_policy_bytes(policy: Mapping[str, Any]) -> bytes:
    """The bytes a limit-policy signature covers."""
    return json.dumps(policy, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sign_policy(policy: Mapping[str, Any], key: Any, signed_at: str) -> dict[str, Any]:
    """Wrap ``policy`` in a signed envelope. Offline signer helper, not runtime.

    ``key`` is a ``remora.crypto.SigningKey`` bound to the LIMIT_POLICY domain:
    the authority that sets the budgets signs, and REMORA verifies with its
    public key, so a REMORA host cannot write itself a larger budget.

    The signature covers ``policy`` only. ``signed_at`` is unsigned metadata
    for the operator: anyone who can write the file can change it, and
    nothing REMORA decides reads it. The policy identity a grant binds is the
    digest of the whole file, so a changed ``signed_at`` still changes it.
    """
    from remora.crypto import SignatureDomain, sign

    signature = sign(SignatureDomain.LIMIT_POLICY, canonical_policy_bytes(policy), key)
    return {"schema": SIGNED_SCHEMA, "policy": dict(policy), "signed_at": signed_at,
            "signature": signature.to_dict()}


def verify_signed_policy(document: Any, keys: Any) -> tuple[dict[str, Any], str]:
    """The policy and the signer's key id, or ``LimitPolicyError`` with the reason.

    ``keys`` are ``remora.crypto.VerificationKey`` objects for the domain.
    ``signed_at`` is not verified and not returned (see :func:`sign_policy`).
    """
    from remora.crypto import Signature, SignatureDomain, verify

    if not isinstance(document, Mapping) or document.get("schema") != SIGNED_SCHEMA:
        raise LimitPolicyError(f"limit policy is not a signed {SIGNED_SCHEMA!r} envelope")
    policy, raw_signature = document.get("policy"), document.get("signature")
    if not isinstance(policy, Mapping) or not isinstance(raw_signature, Mapping):
        raise LimitPolicyError("signed limit policy needs a policy and a signature")
    # A malformed block reads as empty fields, and verify refuses those.
    signature = Signature.from_dict(raw_signature)
    result = verify(SignatureDomain.LIMIT_POLICY, canonical_policy_bytes(policy), signature,
                    list(keys))
    if not result.ok:
        raise LimitPolicyError(f"limit policy signature refused: {result.reason}")
    return dict(policy), result.kid


class _Refused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise LimitPolicyError(f"{what} must be a non-empty string of at most 200 characters")
    return value


def _int(value: Any, what: str, low: int = 0) -> int:
    if type(value) is not int or not low <= value <= MAX_UNITS:
        raise LimitPolicyError(f"{what} must be an integer in [{low}, {MAX_UNITS}]")
    return value


def _scaled(value: Any, scale: int) -> int | None:
    """``value * scale`` as an exact integer, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    scaled = Decimal(str(value)) * scale  # finite int or float: always a valid Decimal
    if scaled != scaled.to_integral_value() or abs(scaled) > MAX_UNITS:
        return None
    return int(scaled)


@dataclass(frozen=True)
class Meter:
    quantity: str
    kind: str
    argument: str | None
    scale: int
    per_call: int
    unit: str | None
    unit_argument: str | None
    resource_argument: str | None
    observed: bool = False
    #: A field of the tool's result that carries the value before the write,
    #: as the controller reports it. Used to account for the actual movement.
    previous_field: str | None = None
    #: Per resource, the scaled value the deployment declares safe (a change
    #: meter only). A write whose new value is exactly that is never refused by
    #: a movement limit and is charged nothing, before or after the fact: a
    #: plant must always be able to go to its safe state through the governed
    #: path. Moving away from it again is charged as any move.
    safe_values: Mapping[str, int] = dataclass_field(default_factory=dict)
    #: Per resource, another resource of this meter whose declared safe value
    #: puts the plant in its safe state (an observed change meter only). While
    #: the plant reports that other resource at its safe value, a move of this
    #: resource is charged nothing, before or after the fact: with delivery
    #: stopped, a dependent setpoint is parked or prepared for the restart.
    #: The fence still applies, and once the other resource leaves its safe
    #: value every move is charged again.
    exempt_while_safe: Mapping[str, str] = dataclass_field(default_factory=dict)

    @classmethod
    def from_dict(cls, tool: str, raw: Any) -> Meter:
        if not isinstance(raw, Mapping):
            raise LimitPolicyError(f"tool {tool!r}: each meter is an object")
        kind = raw.get("kind")
        if kind not in KINDS:
            raise LimitPolicyError(f"tool {tool!r}: kind must be one of {KINDS}")
        argument = raw.get("argument")
        if kind in ("sum", "change"):
            argument = _text(argument, f"tool {tool!r} argument")
        elif argument is not None:
            raise LimitPolicyError(f"tool {tool!r}: a count meter reads no argument")
        unit, unit_argument = raw.get("unit"), raw.get("unit_argument")
        if (unit is None) == (unit_argument is None):
            raise LimitPolicyError(f"tool {tool!r}: declare exactly one of unit, unit_argument")
        resource = raw.get("resource_argument")
        if kind == "change" and resource is None:
            raise LimitPolicyError(f"tool {tool!r}: a change meter needs resource_argument")
        observed = raw.get("observed", False)
        if type(observed) is not bool or (observed and kind != "change"):
            raise LimitPolicyError(f"tool {tool!r}: observed is a boolean, on change meters only")
        previous = raw.get("previous_field")
        if previous is not None and not observed:
            raise LimitPolicyError(f"tool {tool!r}: previous_field needs an observed meter")
        scale = _int(raw.get("scale", 1), "scale", 1)
        safe_raw = raw.get("safe_values")
        safe: dict[str, int] = {}
        if safe_raw is not None:
            if kind != "change":
                raise LimitPolicyError(f"tool {tool!r}: safe_values are for change meters only")
            if not isinstance(safe_raw, Mapping) or not safe_raw:
                raise LimitPolicyError(
                    f"tool {tool!r}: safe_values is a non-empty object of resource to value")
            for resource_id, value in safe_raw.items():
                if not isinstance(resource_id, str) or not resource_id or _SEP in resource_id:
                    raise LimitPolicyError(f"tool {tool!r}: a safe_values key names a resource")
                scaled = _scaled(value, scale)
                if scaled is None:
                    raise LimitPolicyError(
                        f"tool {tool!r}: safe value for {resource_id!r} is not a number at "
                        f"scale {scale}")
                safe[resource_id] = scaled
        exempt_raw = raw.get("exempt_while_safe")
        exempt: dict[str, str] = {}
        if exempt_raw is not None:
            if kind != "change" or not observed:
                raise LimitPolicyError(
                    f"tool {tool!r}: exempt_while_safe is for observed change meters only")
            if not isinstance(exempt_raw, Mapping) or not exempt_raw:
                raise LimitPolicyError(
                    f"tool {tool!r}: exempt_while_safe is a non-empty object of resource to "
                    "resource")
            for resource_id, other in exempt_raw.items():
                if not isinstance(resource_id, str) or not resource_id or _SEP in resource_id:
                    raise LimitPolicyError(
                        f"tool {tool!r}: an exempt_while_safe key names a resource")
                if not isinstance(other, str) or other not in safe or other == resource_id:
                    raise LimitPolicyError(
                        f"tool {tool!r}: exempt_while_safe for {resource_id!r} must name another "
                        "resource with a declared safe value")
                exempt[resource_id] = other
        return cls(
            quantity=_text(raw.get("quantity"), f"tool {tool!r} quantity"), kind=kind,
            argument=argument, scale=scale,
            per_call=_int(raw.get("per_call", 1), "per_call", 1),
            unit=None if unit is None else _text(unit, "unit"),
            unit_argument=None if unit_argument is None else _text(unit_argument,
                                                                    "unit_argument"),
            resource_argument=None if resource is None else _text(resource,
                                                                   "resource_argument"),
            observed=observed,
            previous_field=None if previous is None else _text(previous, "previous_field"),
            safe_values=safe, exempt_while_safe=exempt)


@dataclass(frozen=True)
class Limit:
    limit_id: str
    tenant: str
    quantity: str
    unit: str
    max: int
    window_seconds: int | None
    principal: str  # an id, or "*" for one total shared by every principal
    resource: str | None  # an id, "*" for each resource apart, None for all together

    def matches(self, tenant: str, principal: str, quantity: str, unit: str,
                resource: str | None) -> bool:
        return ((self.tenant, self.quantity, self.unit) == (tenant, quantity, unit)
                and self.principal in ("*", principal)
                and (self.resource in (None, "*") or self.resource == resource))

    def counter_key(self, principal: str, resource: str | None) -> str:
        who = "*" if self.principal == "*" else principal
        what = resource if self.resource == "*" else (self.resource or "*")
        return "\x1f".join((self.limit_id, who, str(what)))

    @property
    def binding(self) -> str:
        """Every declared term, so an edited limit under the same id refuses."""
        terms = "\x1f".join((SCHEMA, self.limit_id, self.tenant, self.quantity, self.unit,
                             str(self.max), str(self.window_seconds), self.principal,
                             str(self.resource)))
        return hashlib.sha256(terms.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Baseline:
    tenant: str
    quantity: str
    resource: str
    value: int  # scaled
    seed_id: str


@dataclass(frozen=True)
class LimitPolicy:
    coverage: str
    meters: Mapping[str, tuple[Meter, ...]]
    limits: tuple[Limit, ...]
    baselines: tuple[Baseline, ...]
    #: Per tool, the arguments whose values identify one operation.
    idempotency: Mapping[str, tuple[str, ...]] = dataclass_field(default_factory=dict)
    #: Per tool, the ``ToolDidNotExecute`` sources whose statement frees a reservation.
    non_execution: Mapping[str, frozenset[str]] = dataclass_field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LimitPolicy:
        if not isinstance(data, Mapping) or data.get("schema") != SCHEMA:
            raise LimitPolicyError(f"limit policy schema must be {SCHEMA!r}")
        coverage = data.get("coverage", "listed")
        if coverage not in COVERAGES:
            raise LimitPolicyError(f"coverage must be one of {COVERAGES}")
        raw_meters = data.get("meters")
        if not isinstance(raw_meters, Mapping) or not raw_meters:
            raise LimitPolicyError("a limit policy meters at least one tool")
        meters: dict[str, tuple[Meter, ...]] = {}
        for tool, raw in raw_meters.items():
            if not isinstance(raw, list | tuple) or not raw:
                raise LimitPolicyError(f"tool {tool!r}: a non-empty list of meters")
            parsed = tuple(Meter.from_dict(tool, m) for m in raw)
            if len({m.quantity for m in parsed}) != len(parsed):
                raise LimitPolicyError(f"tool {tool!r}: one meter per quantity")
            meters[_text(tool, "tool name")] = parsed
        scales: dict[str, int] = {}
        for parsed in meters.values():
            for m in parsed:
                if scales.setdefault(m.quantity, m.scale) != m.scale:
                    raise LimitPolicyError(f"quantity {m.quantity!r} has two scales")
        limits = []
        for raw in data.get("limits") or ():
            if not isinstance(raw, Mapping):
                raise LimitPolicyError("each limit is an object")
            window = raw.get("window_seconds")
            resource = raw.get("resource")
            limits.append(Limit(
                limit_id=_text(raw.get("limit_id"), "limit_id"),
                tenant=_text(raw.get("tenant"), "tenant"),
                quantity=_text(raw.get("quantity"), "quantity"),
                unit=_text(raw.get("unit"), "unit"), max=_int(raw.get("max"), "max"),
                window_seconds=None if window is None else _int(window, "window_seconds", 1),
                principal=_text(raw.get("principal"), "principal"),
                resource=None if resource is None else _text(resource, "resource")))
        if len({lim.limit_id for lim in limits}) != len(limits):
            raise LimitPolicyError("limit_id values must be unique")
        baselines = []
        for raw in data.get("baselines") or ():
            if not isinstance(raw, Mapping):
                raise LimitPolicyError("each baseline is an object")
            quantity = _text(raw.get("quantity"), "baseline quantity")
            if quantity not in scales:
                raise LimitPolicyError(f"baseline for unmetered quantity {quantity!r}")
            value = _scaled(raw.get("value"), scales[quantity])
            if value is None:
                raise LimitPolicyError(f"baseline value for {quantity!r} is not exact at "
                                       f"scale {scales[quantity]}")
            baselines.append(Baseline(
                tenant=_text(raw.get("tenant"), "tenant"), quantity=quantity,
                resource=_text(raw.get("resource"), "resource"), value=value,
                seed_id=_text(raw.get("seed_id"), "seed_id")))
        keys = [(b.tenant, b.quantity, b.resource) for b in baselines]
        if len(set(keys)) != len(keys):
            raise LimitPolicyError("two baselines for one resource")
        raw_idem = data.get("idempotency") or {}
        if not isinstance(raw_idem, Mapping):
            raise LimitPolicyError("idempotency is an object keyed by tool")
        idempotency: dict[str, tuple[str, ...]] = {}
        for tool, raw in raw_idem.items():
            if tool not in meters:
                raise LimitPolicyError(f"idempotency for unmetered tool {tool!r}")
            args = raw.get("key_arguments") if isinstance(raw, Mapping) else None
            if not isinstance(args, list) or not args or len(set(args)) != len(args):
                raise LimitPolicyError(f"tool {tool!r}: key_arguments is a non-empty list "
                                       "of distinct argument names")
            idempotency[tool] = tuple(_text(a, f"tool {tool!r} key argument") for a in args)
        raw_trust = data.get("non_execution")
        if raw_trust is None:
            raw_trust = {}
        if not isinstance(raw_trust, Mapping):
            raise LimitPolicyError("non_execution is an object keyed by tool")
        non_execution: dict[str, frozenset[str]] = {}
        for tool, raw in raw_trust.items():
            if tool not in meters:
                raise LimitPolicyError(f"non_execution for unmetered tool {tool!r}")
            sources = raw.get("trusted_sources") if isinstance(raw, Mapping) else None
            if (not isinstance(sources, list) or not sources
                    or len(set(sources)) != len(sources)):
                raise LimitPolicyError(f"tool {tool!r}: trusted_sources is a non-empty list "
                                       "of distinct source names")
            non_execution[tool] = frozenset(_text(s, f"tool {tool!r} trusted source")
                                            for s in sources)
        return cls(coverage=coverage, meters=meters, limits=tuple(limits),
                   baselines=tuple(baselines), idempotency=idempotency,
                   non_execution=non_execution)

    @property
    def observed_quantities(self) -> frozenset[str]:
        """Quantities whose change is measured from an observed value."""
        return frozenset(m.quantity for meters in self.meters.values() for m in meters
                         if m.observed)

    def exempting_resource(self, quantity: str, resource: str) -> tuple[str, int, int] | None:
        """(other resource, its scaled safe value, the meter's scale) that exempts this one."""
        for meters in self.meters.values():
            for m in meters:
                if m.quantity == quantity and resource in m.exempt_while_safe:
                    other = m.exempt_while_safe[resource]
                    return other, m.safe_values[other], m.scale
        return None

    def safe_value(self, quantity: str, resource: str) -> int | None:
        """The scaled value declared safe for this quantity and resource, or None."""
        for meters in self.meters.values():
            for m in meters:
                if m.quantity == quantity and resource in m.safe_values:
                    return m.safe_values[resource]
        return None

    def baseline(self, tenant: str, quantity: str, resource: str) -> Baseline | None:
        return next((b for b in self.baselines
                     if (b.tenant, b.quantity, b.resource) == (tenant, quantity, resource)),
                    None)


@dataclass(frozen=True)
class Reading:
    """One meter's reading of one call, before the change is computed."""

    meter: Meter
    unit: str
    resource: str | None
    value: int  # scaled amount (sum, count) or scaled new value (change)


#: The tables, in a dialect both backends read. ``{REAL}`` is the backend's
#: double-precision type: SQLite ``REAL`` is 8 bytes, Postgres ``REAL`` is 4
#: and would round epoch seconds.
_DDL = (
    "CREATE TABLE IF NOT EXISTS limit_counter ("
    " counter_key TEXT PRIMARY KEY, binding TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS limit_reservation ("
    " counter_key TEXT NOT NULL REFERENCES limit_counter(counter_key),"
    " operation_id TEXT NOT NULL, request_hash TEXT NOT NULL,"
    " amount INTEGER NOT NULL CHECK(amount >= 0), at {REAL} NOT NULL,"
    " PRIMARY KEY(counter_key, operation_id))",
    "CREATE TABLE IF NOT EXISTS limit_observation ("
    " operation_id TEXT NOT NULL, value_key TEXT NOT NULL,"
    " observed TEXT NOT NULL, charged INTEGER NOT NULL,"
    " PRIMARY KEY(operation_id, value_key))",
    "CREATE TABLE IF NOT EXISTS limit_value ("
    " value_key TEXT PRIMARY KEY, value INTEGER NOT NULL,"
    " status TEXT NOT NULL CHECK(status IN ('settled','pending','unknown')),"
    " operation_id TEXT NOT NULL, seed_id TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS limit_operation ("
    " operation_id TEXT PRIMARY KEY, tenant TEXT NOT NULL,"
    " principal TEXT NOT NULL, tool TEXT NOT NULL, op_key TEXT,"
    " state TEXT NOT NULL CHECK(state IN"
    " ('reserved','started','settled','unknown','released')),"
    " expires_at {REAL}, at {REAL} NOT NULL,"
    " resolved_by TEXT, resolution TEXT)",
    "CREATE INDEX IF NOT EXISTS limit_operation_key ON limit_operation(op_key)",
)

#: Transaction-scoped Postgres advisory lock that serializes every ledger
#: transaction, as ``BEGIN IMMEDIATE`` does on SQLite. One key for the whole
#: ledger: the invariant is a sum over every reservation that matches a
#: limit, and a lock per counter would still need the operation and value
#: rows; serializing the ledger is the proven semantics, and a pilot's limit
#: traffic is far below what that costs.
_PG_LOCK_KEY = 0x52454D4C  # "REML"
_PG_SCHEMES = ("postgres://", "postgresql://")
_PG_KEYWORD = re.compile(r"^\s*[A-Za-z_]+\s*=")


def is_postgres_dsn(spec: str) -> bool:
    """Whether ``spec`` names a PostgreSQL database rather than a SQLite file.

    A libpq URL (``postgresql://...``) or a libpq keyword string
    (``host=... dbname=...``, which ``psycopg.conninfo.make_conninfo``
    produces). A file path is neither.
    """
    return spec.startswith(_PG_SCHEMES) or bool(_PG_KEYWORD.match(spec))


#: The value of ``REMORA_LIMITS_LEDGER_SCOPE`` that declares a host-local
#: ledger deliberate (RMR-AUD-26-010).
LEDGER_SCOPE_SINGLE_HOST = "single_host"


def ledger_topology_problem(ledger: str, *, authority_dsn: str, scope: str) -> str | None:
    """Why this ledger does not fit the deployment's topology, or None.

    A SQLite ledger is one host's file. Authority state on PostgreSQL
    (``REMORA_PG_DSN``) is the shape a second executor host can join, and
    each such host would then keep its own budget and could spend the whole
    limit (SDD unified capability execution v1.1 section 7.1, G04). The
    strict profiles refuse that combination outright; elsewhere it is
    accepted only when the deployment declares the ledger single-host, so a
    multi-host setup cannot reach it by copying a single-host configuration
    and adding a replica. With the authority state on SQLite too, everything
    is one host's by construction and nothing needs declaring.
    """
    if scope not in ("", LEDGER_SCOPE_SINGLE_HOST):
        return (f"REMORA_LIMITS_LEDGER_SCOPE={scope!r} is not {LEDGER_SCOPE_SINGLE_HOST!r}; "
                "leave it unset for a PostgreSQL ledger")
    if is_postgres_dsn(ledger) or not authority_dsn or scope == LEDGER_SCOPE_SINGLE_HOST:
        return None
    return ("REMORA_LIMITS_LEDGER is a host-local SQLite file while REMORA_PG_DSN holds the "
            "authority state, so a second executor host would keep its own budget and could "
            "spend the whole limit. Use a PostgreSQL DSN for REMORA_LIMITS_LEDGER, or set "
            f"REMORA_LIMITS_LEDGER_SCOPE={LEDGER_SCOPE_SINGLE_HOST} to declare that exactly "
            "one host runs executors")


class _PgConnection:
    """A psycopg connection that takes this module's ``?`` SQL.

    Every statement in this module is written once, with ``?`` placeholders
    and no ``?`` or ``%`` anywhere else, so the rewrite is textual. psycopg's
    ``execute`` returns a cursor with ``fetchone`` and ``fetchall``, as
    sqlite3's does, so the callers do not know which backend they hold.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        return self._conn.execute(sql.replace("?", "%s"), params)


class LimitLedger:
    """Ledger of reservations and last values: one host's SQLite file, or a
    PostgreSQL database every executor shares.

    ``spec`` is a file path, or a ``postgres://`` / ``postgresql://`` DSN.
    On SQLite every transaction is ``BEGIN IMMEDIATE``; on Postgres every
    transaction takes one advisory lock (``_PG_LOCK_KEY``), so in both the
    reads and writes of a reservation are serial against every other
    executor's, and the sum of reservations inside a window never passes the
    limit across hosts. The schema is created on first open, under the same
    lock, so two executors opening a fresh database do not race the catalog.

    Kept in ``remora/enforcement``: the enforcement core does not import the
    verification library (tests/verification/test_architecture_boundary.py).
    """

    def __init__(self, spec: str | Path) -> None:
        spec = str(spec)
        self.dsn = spec if is_postgres_dsn(spec) else ""
        self.path = "" if self.dsn else spec
        if not self.dsn:
            from remora.persistence.sqlite_path import refuse_memory_db

            refuse_memory_db(self.path, what="cumulative limit ledger")
        with self.transaction() as conn:
            real = "DOUBLE PRECISION" if self.dsn else "REAL"
            for statement in _DDL:
                conn.execute(statement.replace("{REAL}", real))
            self._migrate(conn)

    @property
    def shared(self) -> bool:
        """Whether more than one host can hold this ledger (a Postgres DSN)."""
        return bool(self.dsn)

    #: Columns added after the first ledgers were created. A ledger from an
    #: earlier version gains them on open; their defaults describe the old
    #: rows truthfully (nothing recorded, no evidence named).
    _ADDED_COLUMNS = (
        ("evidence_ref", "TEXT"),
        ("reason", "TEXT"),
        ("resolved_at", "{REAL}"),
        ("audit_recorded", "INTEGER NOT NULL DEFAULT 0"),
    )

    def _migrate(self, conn: Any) -> None:
        if self.dsn:
            for name, declaration in self._ADDED_COLUMNS:
                conn.execute(f"ALTER TABLE limit_operation ADD COLUMN IF NOT EXISTS {name} "
                             f"{declaration.replace('{REAL}', 'DOUBLE PRECISION')}")
            return
        present = {row[1] for row in conn.execute("PRAGMA table_info(limit_operation)")}
        for name, declaration in self._ADDED_COLUMNS:
            if name not in present:
                conn.execute(f"ALTER TABLE limit_operation ADD COLUMN {name} "
                             f"{declaration.replace('{REAL}', 'REAL')}")

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        """One connection, committed on a clean exit and rolled back on an exception."""
        if self.dsn:
            import psycopg  # type: ignore[import-not-found]

            with psycopg.connect(self.dsn) as conn:
                yield _PgConnection(conn)
            return
        sqlite = sqlite3.connect(self.path, timeout=5.0)
        try:
            sqlite.execute("PRAGMA foreign_keys=ON")
            with sqlite:
                yield sqlite
        finally:
            sqlite.close()

    def transaction(self) -> Any:
        """One serialized transaction: reads and writes in it are serial across executors.

        ``BEGIN IMMEDIATE`` on SQLite; on Postgres the ledger's advisory lock,
        held until the transaction commits or rolls back.
        """
        @contextmanager
        def _tx() -> Iterator[Any]:
            with self._connect() as conn:
                if self.dsn:
                    conn.execute("SELECT pg_advisory_xact_lock(?)", (_PG_LOCK_KEY,))
                else:
                    conn.execute("BEGIN IMMEDIATE")
                yield conn
        return _tx()

    @staticmethod
    def used(conn: Any, key: str, binding: str,
             window_seconds: int | None, now: float) -> int:
        row = conn.execute("SELECT binding FROM limit_counter WHERE counter_key=?",
                           (key,)).fetchone()
        if row is not None and row[0] != binding:
            raise _Refused(CHANGED)
        since = -math.inf if window_seconds is None else now - window_seconds
        total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM limit_reservation "
            "WHERE counter_key=? AND at>?", (key, since)).fetchone()[0]
        return int(total)

    @staticmethod
    def prior(conn: Any, key: str, operation_id: str) -> tuple[str, int] | None:
        row = conn.execute("SELECT request_hash,amount FROM limit_reservation "
                           "WHERE counter_key=? AND operation_id=?",
                           (key, operation_id)).fetchone()
        return None if row is None else (row[0], int(row[1]))

    @staticmethod
    def record(conn: Any, key: str, binding: str, operation_id: str,
               request_hash: str, amount: int, now: float) -> None:
        conn.execute("INSERT INTO limit_counter VALUES(?,?) ON CONFLICT DO NOTHING", (key, binding))
        conn.execute("INSERT INTO limit_reservation VALUES(?,?,?,?,?)",
                     (key, operation_id, request_hash, amount, now))

    @staticmethod
    def value(conn: Any, key: str) -> tuple[int, str, str, str] | None:
        row = conn.execute("SELECT value,status,operation_id,seed_id FROM limit_value "
                           "WHERE value_key=?", (key,)).fetchone()
        return None if row is None else (int(row[0]), row[1], row[2], row[3])

    @staticmethod
    def set_value(conn: Any, key: str, value: int, status: str,
                  operation_id: str, seed_id: str) -> None:
        conn.execute("INSERT INTO limit_value VALUES(?,?,?,?,?) ON CONFLICT(value_key) DO "
                     "UPDATE SET value=excluded.value, status=excluded.status, "
                     "operation_id=excluded.operation_id, seed_id=excluded.seed_id",
                     (key, value, status, operation_id, seed_id))

    def settle(self, operation_id: str, ok: bool) -> list[tuple[str, int]]:
        """Record whether the call reserved under ``operation_id`` ran.

        Returns the (value key, target) pairs it settled.
        """
        with self._connect() as conn:
            rows = conn.execute("SELECT value_key,value FROM limit_value WHERE operation_id=? "
                                "AND status='pending'", (operation_id,)).fetchall()
            conn.execute("UPDATE limit_value SET status=? WHERE operation_id=? "
                         "AND status='pending'", ("settled" if ok else "unknown", operation_id))
        return [(str(key), int(value)) for key, value in rows]

    @staticmethod
    def record_observation(conn: Any, operation_id: str, value_key: str,
                           observed: Decimal, charged: int) -> None:
        conn.execute("INSERT INTO limit_observation VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                     (operation_id, value_key, str(observed), charged))

    def observations(self, operation_id: str) -> list[tuple[str, Decimal, int]]:
        """(value key, value observed at reservation, amount charged) for one operation."""
        with self._connect() as conn:
            rows = conn.execute("SELECT value_key,observed,charged FROM limit_observation "
                                "WHERE operation_id=?", (operation_id,)).fetchall()
        return [(str(k), Decimal(str(v)), int(c)) for k, v, c in rows]

    def charges(self, operation_id: str) -> list[tuple[str, int]]:
        """(counter key, amount) this operation reserved."""
        with self._connect() as conn:
            rows = conn.execute("SELECT counter_key,amount FROM limit_reservation "
                                "WHERE operation_id=?", (operation_id,)).fetchall()
        return [(str(k), int(a)) for k, a in rows]

    def release(self, operation_id: str) -> None:
        """Return an operation's reservations. Only for a call that provably did not run."""
        with self._connect() as conn:
            self.release_in(conn, operation_id)

    @staticmethod
    def release_in(conn: Any, operation_id: str) -> None:
        """``release`` inside an open transaction.

        A change meter's value row is put back to the value the reservation
        was measured from and settled, whatever status it holds: nothing was
        written, so nothing is unknown.
        """
        for key, observed in conn.execute(
                "SELECT value_key,observed FROM limit_observation WHERE operation_id=?",
                (operation_id,)).fetchall():
            conn.execute("UPDATE limit_value SET value=?, status='settled' "
                         "WHERE value_key=? AND operation_id=?",
                         (int(Decimal(str(observed)).to_integral_value()), key, operation_id))
        conn.execute("DELETE FROM limit_reservation WHERE operation_id=?", (operation_id,))
        conn.execute("DELETE FROM limit_observation WHERE operation_id=?", (operation_id,))
        conn.execute("UPDATE limit_operation SET state='released' WHERE operation_id=?",
                     (operation_id,))

    @staticmethod
    def operation(conn: Any, operation_id: str) -> dict[str, Any] | None:
        row = conn.execute(f"SELECT {_OPERATION_SELECT} FROM limit_operation "  # noqa: S608 - fixed column list
                           "WHERE operation_id=?", (operation_id,)).fetchone()
        return None if row is None else dict(zip(_OPERATION_FIELDS, row, strict=True))

    def unrecorded_resolutions(self, tenant: str) -> list[dict[str, Any]]:
        """Resolved operations of ``tenant`` whose chain record has not been written, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_OPERATION_SELECT} FROM limit_operation WHERE tenant=? AND "  # noqa: S608
                "resolved_by IS NOT NULL AND audit_recorded=0 ORDER BY resolved_at, at",
                (tenant,)).fetchall()
        return [dict(zip(_OPERATION_FIELDS, r, strict=True)) for r in rows]

    def mark_recorded(self, operation_id: str) -> None:
        """The chain now carries this operation's resolution."""
        with self._connect() as conn:
            conn.execute("UPDATE limit_operation SET audit_recorded=1 WHERE operation_id=?",
                         (operation_id,))

    @staticmethod
    def same_key(conn: Any, op_key: str, operation_id: str) -> list[str]:
        """States of other operations with this key that have not been released."""
        rows = conn.execute("SELECT state FROM limit_operation WHERE op_key=? AND "
                            "operation_id!=? AND state!='released'",
                            (op_key, operation_id)).fetchall()
        return [str(r[0]) for r in rows]

    def finish(self, operation_id: str, ok: bool) -> None:
        """Record that a reserved or started operation ran, or ended unknown."""
        with self._connect() as conn:
            conn.execute("UPDATE limit_operation SET state=? WHERE operation_id=? AND "
                         "state IN ('reserved','started')",
                         ("settled" if ok else "unknown", operation_id))

    def operations(self, tenant: str, state: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_OPERATION_SELECT} FROM limit_operation WHERE tenant=? AND state=? "  # noqa: S608
                "ORDER BY at", (tenant, state)).fetchall()
        return [dict(zip(_OPERATION_FIELDS, r, strict=True)) for r in rows]

    def debit(self, key: str, operation_id: str, amount: int, now: float) -> None:
        """Charge movement found after the fact; it is not checked against the limit."""
        with self._connect() as conn:
            conn.execute("INSERT INTO limit_reservation VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                         (key, operation_id, "after-the-fact", amount, now))

    def observe(self, value_key: str, value: int) -> None:
        """Replace a settled or unknown value with what was observed."""
        with self._connect() as conn:
            conn.execute("UPDATE limit_value SET value=?, status='settled' WHERE value_key=? "
                         "AND status!='pending'", (value, value_key))


_OPERATION_FIELDS = ("operation_id", "tenant", "principal", "tool", "op_key", "state",
                     "expires_at", "at", "resolved_by", "resolution", "evidence_ref", "reason",
                     "resolved_at", "audit_recorded")
_OPERATION_SELECT = ",".join(_OPERATION_FIELDS)


def _epoch(now: str | float | None) -> float:
    if now is None:
        return time.time()
    if isinstance(now, int | float):
        return float(now)
    parsed = datetime.fromisoformat(now)
    if parsed.tzinfo is None:
        # The lease verifier reads a naive stamp as UTC; the window must too,
        # or the host's zone shifts every reservation by its offset.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


class LimitGuard:
    """Measures a call, and reserves it against every limit it matches."""

    def __init__(self, policy: LimitPolicy, ledger: LimitLedger,
                 is_write: Callable[[str], bool | None] | None = None,
                 observer: Callable[[str, str, str], Any] | None = None,
                 in_force: Callable[[], bool] | None = None,
                 evidence: Callable[[str, Mapping[str, Any], str], Any] | None = None,
                 require_keys: bool = False) -> None:
        """``in_force`` answers whether ``policy`` is still the one deployed.

        The deployment builds the guard once, from the policy it verified at
        startup, while a grant binds the digest of the policy file it reads
        at that moment. When the two part (the file replaced on the same path
        by a smaller budget, a larger one, or one whose signature does not
        verify), every call refuses with ``limit_policy_changed`` until a
        restart verifies the new policy: neither budget is enforced for a
        grant bound to the other. Reservations already made are still
        released and settled, so the ledger stays exact. A failing check
        counts as changed.

        ``evidence(tenant, operation, evidence_ref)`` asks the deployment's
        authoritative source (the rail, the plant) whether the operation a
        reviewer wants to resolve ran, and returns a mapping whose
        ``executed`` is True or False. :meth:`resolve` refuses without one,
        when it fails or cannot tell, and when it disagrees with the
        reviewer. ``require_keys`` refuses a metered write tool that
        declares no idempotency key.
        """
        if policy.observed_quantities and observer is None:
            raise LimitPolicyError("observed change meters need an observer")
        self.policy = policy
        self.ledger = ledger
        self.is_write = is_write
        self.observer = observer
        self.in_force = in_force
        self.evidence = evidence
        self.require_keys = require_keys

    def _changed(self) -> bool:
        if self.in_force is None:
            return False
        try:
            return not self.in_force()
        except Exception:
            return True

    def _observe(self, tenant: str, quantity: str, resource: str, scale: int) -> Decimal | None:
        """The observed value, scaled; None when it cannot be read as a finite number."""
        if self.observer is None:
            return None
        try:
            raw = self.observer(tenant, quantity, resource)
        except Exception:
            return None
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            return None
        if isinstance(raw, float) and not math.isfinite(raw):
            return None
        return Decimal(str(raw)) * scale

    def governs(self, tool_name: str) -> bool:
        if self._changed():
            return True  # the deployed policy may meter it; refuse rather than guess
        return tool_name in self.policy.meters or self.policy.coverage == "all_writes"

    def _write(self, tool_name: str) -> bool | None:
        """Whether the deployment says ``tool_name`` writes; None when it cannot say."""
        try:
            return self.is_write(tool_name) if self.is_write is not None else None
        except Exception:
            return None

    def _coverage_refusal(self, tool_name: str) -> str | None:
        if tool_name in self.policy.meters or self.policy.coverage != "all_writes":
            return None
        write = self._write(tool_name)
        if write is None:
            return COVERAGE_UNKNOWN
        return TOOL_UNMETERED if write else None

    def _key_refusal(self, tool_name: str) -> str | None:
        """Under ``require_keys``, a metered write tool must declare its key."""
        if not self.require_keys or tool_name in self.policy.idempotency:
            return None
        write = self._write(tool_name)
        if write is None:
            return COVERAGE_UNKNOWN
        return KEY_UNDECLARED if write else None

    def readings(self, tool_name: str, arguments: Any) -> list[Reading]:
        """What the call consumes per meter; raises ``_Refused`` when unreadable."""
        args = arguments if isinstance(arguments, Mapping) else {}
        out = []
        for meter in self.policy.meters.get(tool_name, ()):
            if meter.unit_argument is not None:
                unit = args.get(meter.unit_argument)
                if not isinstance(unit, str) or not unit or len(unit) > 200 or _SEP in unit:
                    raise _Refused(UNIT_INVALID)
            else:
                unit = meter.unit or ""
            resource = None
            if meter.resource_argument is not None:
                resource = args.get(meter.resource_argument)
                if (not isinstance(resource, str) or not resource or len(resource) > 200
                        or _SEP in resource):
                    raise _Refused(RESOURCE_INVALID)
            if meter.kind == "count":
                value = meter.per_call
            else:
                scaled = _scaled(args.get(meter.argument or ""), meter.scale)
                if scaled is None or (meter.kind == "sum" and scaled < 1):
                    raise _Refused(AMOUNT_INVALID)
                value = scaled
            out.append(Reading(meter, unit, resource, value))
        return out

    def _plan(self, conn: Any, *, tenant: str, principal: str,
              readings: list[Reading], operation_id: str, request_hash: str,
              now: float, observed: Mapping[int, Decimal] | None = None,
              exempt: frozenset[int] = frozenset(),
              ) -> tuple[bool, list[tuple[Limit, str, int]], list[tuple[str, int, str]],
                         list[tuple[str, Decimal, int]]]:
        """Charges and value updates for this call, checked against every limit.

        Returns (already reserved, charges, value updates). Raises ``_Refused``.
        """
        charges: list[tuple[Limit, str, int]] = []
        values: list[tuple[str, int, str]] = []
        seen_at: list[tuple[str, Decimal, int]] = []
        #: Counters whose charge here is a move to a declared safe value.
        safe_keys: set[str] = set()
        for index, reading in enumerate(readings):
            m = reading.meter
            amount: int | None = reading.value
            to_safe = (m.kind == "change" and reading.resource is not None
                       and m.safe_values.get(reading.resource) == reading.value) or index in exempt
            if m.kind == "change" and m.observed:
                resource = reading.resource or ""
                value_key = "\x1f".join((tenant, m.quantity, resource))
                state = self.ledger.value(conn, value_key)
                if state is not None and state[2] == operation_id:
                    amount = None  # a retry of this operation: its charge is recorded
                elif state is not None and state[1] == "pending":
                    raise _Refused(RESOURCE_BUSY)
                else:
                    # Measured from the plant, not from the last value let
                    # through, so a change made outside REMORA is not counted
                    # and one REMORA made is. Rounded up: never under-counted.
                    seen = (observed or {})[index]
                    amount = math.ceil(abs(reading.value - seen))
                    seen_at.append((value_key, seen, amount))
                values.append((value_key, reading.value, "observed"))
            elif m.kind == "change":
                resource = reading.resource or ""
                value_key = "\x1f".join((tenant, m.quantity, resource))
                base = self.policy.baseline(tenant, m.quantity, resource)
                state = self.ledger.value(conn, value_key)
                if base is not None and (state is None or state[3] != base.seed_id):
                    state = (base.value, "settled", "", base.seed_id)  # a new seed resets
                if state is None:
                    raise _Refused(BASELINE_UNKNOWN)
                last, status, owner, seed_id = state
                if owner == operation_id:
                    amount = None  # a retry of this operation: its charge is recorded
                elif status == "pending":
                    raise _Refused(RESOURCE_BUSY)
                elif status == "unknown":
                    raise _Refused(BASELINE_UNKNOWN)
                else:
                    amount = abs(reading.value - last)
                    # Kept so a fence refusal, which writes nothing, can put
                    # the value back instead of leaving the resource unknown.
                    seen_at.append((value_key, Decimal(last), amount))
                values.append((value_key, reading.value, seed_id))
            matching = [lim for lim in self.policy.limits
                        if lim.matches(tenant, principal, m.quantity, reading.unit,
                                       reading.resource)]
            if not matching:
                raise _Refused(UNDECLARED)
            if to_safe and amount is not None:
                amount = 0  # the move to the safe state is never charged
            for lim in matching:
                key = lim.counter_key(principal, reading.resource)
                charges.append((lim, key, -1 if amount is None else amount))
                if to_safe:
                    safe_keys.add(key)
        priors = [self.ledger.prior(conn, key, operation_id) for _, key, _ in charges]
        if charges and all(p is not None for p in priors):
            for (_, _, amount), prior in zip(charges, priors, strict=True):
                if prior is None or prior[0] != request_hash or amount not in (-1, prior[1]):
                    raise _Refused(CHANGED)
            return True, charges, values, seen_at
        if any(p is not None for p in priors) or any(a == -1 for _, _, a in charges):
            raise _Refused(CHANGED)
        # Each charge has its own counter: one meter per quantity, one quantity per limit.
        for lim, key, amount in charges:
            if key in safe_keys:
                continue  # a full counter must not stop the move to the safe state
            if self.ledger.used(conn, key, lim.binding, lim.window_seconds, now) + amount > lim.max:
                raise _Refused(EXCEEDED)
        return False, charges, values, seen_at

    def operation_key(self, tenant: str, tool_name: str, arguments: Any) -> str | None:
        """The idempotency key of a call, None when its tool declares none.

        Raises ``_Refused`` when a declared key argument is missing or not a
        plain value: a payment that cannot be identified must not run.
        """
        names = self.policy.idempotency.get(tool_name)
        if not names:
            return None
        args = arguments if isinstance(arguments, Mapping) else {}
        values = []
        for name in names:
            value = args.get(name)
            if isinstance(value, bool) or not isinstance(value, str | int) or value == "":
                raise _Refused(IDEMPOTENCY_KEY_INVALID)
            values.append(value)
        body = json.dumps([tenant, tool_name, list(names), values], separators=(",", ":"),
                          ensure_ascii=False)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    @staticmethod
    def _duplicate(conn: Any, op_key: str | None,
                   operation_id: str) -> str | None:
        """The refusal for another live operation with the same key, or None."""
        if op_key is None:
            return None
        states = LimitLedger.same_key(conn, op_key, operation_id)
        if "unknown" in states:
            return OUTCOME_UNKNOWN
        if "settled" in states:
            return DUPLICATE
        if states:
            return DUPLICATE_IN_FLIGHT
        return None

    @staticmethod
    def _release_expired(conn: Any, now: float) -> None:
        """Release reservations whose lease expired before the tool was started.

        Such a lease can no longer be dispatched, and ``begin`` refuses one
        released here, so its reservation would otherwise hold the limit for
        nothing. A started operation is never released by time.
        """
        for (operation_id,) in conn.execute(
                "SELECT operation_id FROM limit_operation WHERE state='reserved' AND "
                "expires_at IS NOT NULL AND expires_at<?", (now,)).fetchall():
            LimitLedger.release_in(conn, operation_id)

    def _run(self, *, tenant: str, principal: str, tool_name: str, arguments: Any,
             operation_id: str, request_hash: str, now: str | float | None,
             write: bool, expires_at: str | float | None = None) -> str | None:
        if self._changed():
            return POLICY_CHANGED
        refusal = self._coverage_refusal(tool_name)
        if refusal is not None:
            return refusal
        if tool_name not in self.policy.meters:
            return None
        refusal = self._key_refusal(tool_name)
        if refusal is not None:
            return refusal
        if not principal:
            return PRINCIPAL_MISSING
        if _SEP in principal:
            return PRINCIPAL_INVALID  # it would collide with another principal's key
        try:
            readings = self.readings(tool_name, arguments)
            observed: dict[int, Decimal] = {}
            for index, reading in enumerate(readings):
                if reading.meter.observed:
                    seen = self._observe(tenant, reading.meter.quantity, reading.resource or "",
                                         reading.meter.scale)
                    if seen is None:
                        return OBSERVATION_UNAVAILABLE
                    observed[index] = seen
            exempt = frozenset(index for index, reading in enumerate(readings)
                               if self._exempt_now(tenant, reading.meter.quantity,
                                                   reading.resource or ""))
            at = _epoch(now)
            op_key = self.operation_key(tenant, tool_name, arguments)
            with self.ledger.transaction() as conn:
                self._release_expired(conn, at)
                mine = self.ledger.operation(conn, operation_id)
                if mine is not None and mine["state"] == "released":
                    return RESERVATION_RELEASED
                duplicate = self._duplicate(conn, op_key, operation_id)
                if duplicate is not None:
                    return duplicate
                done, charges, values, seen_at = self._plan(
                    conn, tenant=tenant, principal=principal, readings=readings,
                    operation_id=operation_id, request_hash=request_hash, now=at,
                    observed=observed, exempt=exempt)
                if write and not done:
                    for lim, key, amount in charges:
                        self.ledger.record(conn, key, lim.binding, operation_id,
                                           request_hash, amount, at)
                    for value_key, value, seed_id in values:
                        self.ledger.set_value(conn, value_key, value, "pending",
                                              operation_id, seed_id)
                    for value_key, seen, amount in seen_at:
                        self.ledger.record_observation(conn, operation_id, value_key, seen,
                                                       amount)
                    conn.execute(
                        "INSERT INTO limit_operation(operation_id,tenant,principal,"
                        "tool,op_key,state,expires_at,at) VALUES(?,?,?,?,?,'reserved',?,?) "
                        "ON CONFLICT DO NOTHING",
                        (operation_id, tenant, principal, tool_name, op_key,
                         None if expires_at is None else _epoch(expires_at), at))
        except _Refused as exc:
            return exc.reason
        except Exception:
            return LEDGER_UNAVAILABLE
        return None

    def preview(self, *, tenant: str, principal: str, tool_name: str, arguments: Any,
                now: str | float | None = None) -> str | None:
        """The refusal this call would get now; reserves nothing.

        Advisory: the reservation at dispatch decides, and other calls may
        reserve in between.
        """
        return self._run(tenant=tenant, principal=principal, tool_name=tool_name,
                         arguments=arguments, operation_id="preview",
                         request_hash="preview", now=now, write=False)

    def reserve(self, *, tenant: str, principal: str, tool_name: str, arguments: Any,
                operation_id: str, request_hash: str,
                now: str | float | None = None,
                expires_at: str | float | None = None) -> str | None:
        """Reserve the call against every limit it matches; None when it may run.

        ``operation_id`` names the lease, so a retry of one lease (a crash
        between this reservation and the nonce consumption) finds its own
        reservation and is not charged twice. ``expires_at`` is the lease's
        expiry: a reservation whose lease expired before ``begin`` is released.
        """
        return self._run(tenant=tenant, principal=principal, tool_name=tool_name,
                         arguments=arguments, operation_id=operation_id,
                         request_hash=request_hash, now=now, write=True,
                         expires_at=expires_at)

    def begin(self, operation_id: str) -> str | None:
        """Mark the operation started, just before the tool is invoked; the refusal, or None.

        Serialized with the release of expired reservations: once this
        returns None the reservation can no longer be released by time, and
        once it was released this refuses and the tool must not run.
        """
        try:
            with self.ledger.transaction() as conn:
                row = self.ledger.operation(conn, operation_id)
                if row is None:
                    return None  # reserved before this ledger kept operations
                if row["state"] == "released":
                    return RESERVATION_RELEASED
                if row["state"] == "reserved":
                    conn.execute("UPDATE limit_operation SET state='started' "
                                 "WHERE operation_id=?", (operation_id,))
        except Exception:
            return LEDGER_UNAVAILABLE
        return None

    def unresolved(self, tenant: str) -> list[dict[str, Any]]:
        """Operations of ``tenant`` whose outcome is unknown, oldest first, with their charges."""
        out = []
        for row in self.ledger.operations(tenant, "unknown"):
            out.append({**{k: row[k] for k in ("operation_id", "principal", "tool", "at")},
                        "charges": [{"counter": k.split(_SEP, 1)[0], "amount": a}
                                    for k, a in self.ledger.charges(row["operation_id"])]})
        return out

    def did_not_execute(self, operation_id: str, tool_name: str, source: str) -> bool:
        """Act on an adapter's statement that the call did not run.

        Returns True when the statement came from a source the policy trusts
        for ``tool_name`` and the reservation was returned. Otherwise the
        call is settled as unknown, exactly as a call that raised anything
        else: the budget stays held and a reviewer resolves it with checked
        evidence. An adapter the authority did not name cannot free budget
        by claiming nothing happened.
        """
        if source in self.policy.non_execution.get(tool_name, frozenset()):
            self.ledger.release(operation_id)
            return True
        self.settle(operation_id, ok=False)
        return False

    @staticmethod
    def _resolvable(conn: Any, tenant: str, operation_id: str,
                    resolved_by: str) -> tuple[dict[str, Any] | None, str | None]:
        row = LimitLedger.operation(conn, operation_id)
        if row is None or row["tenant"] != tenant:
            return None, NOT_FOUND
        if row["state"] != "unknown":
            return None, NOT_UNKNOWN
        if row["principal"] == resolved_by:
            return None, RESOLVER_IS_PRINCIPAL
        return row, None

    def _check_evidence(self, tenant: str, operation: Mapping[str, Any], evidence_ref: str,
                        executed: bool) -> str | None:
        """Ask the deployment's source whether the operation ran; the refusal, or None."""
        if self.evidence is None:
            return EVIDENCE_UNCHECKED
        try:
            verdict = self.evidence(tenant, operation, evidence_ref)
        except Exception:
            return EVIDENCE_UNAVAILABLE
        answer = verdict.get("executed") if isinstance(verdict, Mapping) else None
        if not isinstance(answer, bool):
            return EVIDENCE_UNAVAILABLE
        return None if answer is executed else EVIDENCE_DISPUTED

    def resolve(self, *, tenant: str, operation_id: str, executed: bool,
                resolved_by: str, reason: str = "", evidence_ref: str = "") -> str | None:
        """Settle an unknown outcome from what the rail or plant says; the refusal, or None.

        ``executed=False`` releases the reservation (and puts a change
        meter's value back); ``executed=True`` keeps it and settles the
        operation, so a duplicate refuses as ``limit_duplicate_operation``.
        Only an operation in ``unknown`` can be resolved, only within its
        tenant, and not by the principal it was charged to: an agent must
        not free its own budget.

        The reviewer's statement is checked, not taken: the guard's
        ``evidence`` callable asks the authoritative source about
        ``evidence_ref`` outside the ledger transaction, and the resolution
        proceeds only when it answers and agrees. Without a checker nothing
        can be resolved and every unknown outcome keeps its budget.
        """
        if not resolved_by:
            return RESOLVER_IS_PRINCIPAL
        try:
            with self.ledger.transaction() as conn:
                row, refusal = self._resolvable(conn, tenant, operation_id, resolved_by)
            if refusal is not None or row is None:
                return refusal
            # Outside the transaction: the source is remote, and the ledger
            # must not be locked while it answers.
            refusal = self._check_evidence(tenant, row, evidence_ref, executed)
            if refusal is not None:
                return refusal
            with self.ledger.transaction() as conn:
                # Re-read: another reviewer may have resolved it meanwhile.
                row, refusal = self._resolvable(conn, tenant, operation_id, resolved_by)
                if refusal is not None:
                    return refusal
                if executed:
                    conn.execute("UPDATE limit_operation SET state='settled' "
                                 "WHERE operation_id=?", (operation_id,))
                    conn.execute("UPDATE limit_value SET status='settled' WHERE "
                                 "operation_id=? AND status='unknown'", (operation_id,))
                else:
                    LimitLedger.release_in(conn, operation_id)
                resolution = ("executed" if executed else "not_executed")
                if evidence_ref:
                    resolution += f" ({evidence_ref} checked)"
                if reason:
                    resolution += f": {reason}"
                # The ledger is the record of the resolution; the chain is its
                # projection. audit_recorded stays 0 until the chain carries
                # it, so a crash in between leaves a visible, recoverable gap
                # (unrecorded_resolutions), never an undocumented release.
                conn.execute("UPDATE limit_operation SET resolved_by=?, resolution=?, "
                             "evidence_ref=?, reason=?, resolved_at=?, audit_recorded=0 "
                             "WHERE operation_id=?",
                             (resolved_by, resolution, evidence_ref, reason, time.time(),
                              operation_id))
        except Exception:
            return LEDGER_UNAVAILABLE
        return None

    def unrecorded_resolutions(self, tenant: str) -> list[dict[str, Any]]:
        """Resolutions the ledger holds that no chain record carries yet, oldest first.

        The caller projects each one to the audit chain and then calls
        :meth:`mark_recorded`. Idempotent by construction when the chain
        append is keyed by the operation: a crash after the append and before
        the mark re-projects the same key, which the chain refuses.
        """
        return self.ledger.unrecorded_resolutions(tenant)

    def mark_recorded(self, operation_id: str) -> None:
        self.ledger.mark_recorded(operation_id)

    def compare(self, tool_name: str, wire: Any, invocation: Any) -> str | None:
        """Refuse a resolved invocation that would meter differently from the wire form."""
        if self._changed():
            return POLICY_CHANGED
        if tool_name not in self.policy.meters:
            return None
        try:
            same = self.readings(tool_name, wire) == self.readings(tool_name, invocation)
        except _Refused as exc:
            return exc.reason
        return None if same else INVOCATION_DIFFERS

    def _scale_of(self, quantity: str) -> int:
        return next(m.scale for meters in self.policy.meters.values() for m in meters
                    if m.quantity == quantity)

    def _exempt_now(self, tenant: str, quantity: str, resource: str) -> bool:
        """Whether the plant reports the resource that exempts this one at its safe value.

        Unreadable is not safe: an observation that fails leaves the move charged.
        """
        exempting = self.policy.exempting_resource(quantity, resource)
        if exempting is None:
            return False
        other, safe, scale = exempting
        seen = self._observe(tenant, quantity, other, scale)
        return seen is not None and seen == safe

    def fence(self, operation_id: str) -> str | None:
        """Read each observed resource again just before the write.

        None when every value is still the one the reservation was charged
        from; otherwise the refusal, and the write must not happen. This
        narrows the window between reading the plant and writing to it; it
        cannot close it. Only a conditional write at the controller can.
        """
        if self._changed():
            return POLICY_CHANGED
        observed = self.policy.observed_quantities
        for value_key, seen, _ in self.ledger.observations(operation_id):
            tenant, quantity, resource = value_key.split("\x1f")
            if quantity not in observed:
                continue  # a tracked meter's row holds its last value, not a reading
            safe = self.policy.safe_value(quantity, resource)
            if safe is not None:
                with self.ledger.transaction() as conn:
                    state = self.ledger.value(conn, value_key)
                if state is not None and state[0] == safe:  # this operation holds the row
                    continue  # going to the safe state is right whatever the plant did meanwhile
            now_seen = self._observe(tenant, quantity, resource, self._scale_of(quantity))
            if now_seen is None:
                return OBSERVATION_UNAVAILABLE
            if now_seen != seen:
                return STATE_CHANGED
        return None

    def release(self, operation_id: str) -> None:
        """Give back what a call reserved when the write provably did not happen.

        The dispatcher calls this after the fence refused, when the tool was
        never invoked; :meth:`did_not_execute` calls it for a trusted
        ``ToolDidNotExecute``. The lease's nonce is spent in both cases, so
        the lease cannot run later under the same reservation. Every other
        refusal after a reservation keeps it: the same lease may be retried
        until it expires.
        """
        self.ledger.release(operation_id)

    def _account(self, operation_id: str, result: Any, records: list[dict[str, Any]],
                 now: float) -> None:
        """Charge movement the controller reports beyond what was reserved.

        ``previous_field`` in the tool's result is the value before the write,
        as the controller saw it. If the move from there to where the plant
        ended up is larger than the reservation (the plant changed between
        the last read and the write), the difference is charged to every
        counter this operation reserved for that quantity, without a limit
        check: it has already happened. Later changes then meet the limit.
        """
        if not isinstance(result, Mapping):
            return
        fields = {m.quantity: m.previous_field for meters in self.policy.meters.values()
                  for m in meters if m.previous_field}
        limit_quantity = {lim.limit_id: lim.quantity for lim in self.policy.limits}
        charged_at = {k: c for k, _, c in self.ledger.observations(operation_id)}
        charges = self.ledger.charges(operation_id)
        for record in records:
            if self.policy.safe_value(record["quantity"], record["resource"]) == record["target"]:
                continue  # a move to the safe state is charged nothing, after the fact either
            if self._exempt_now(record["tenant"], record["quantity"], record["resource"]):
                continue  # nor a move made while the plant is in its safe state
            field = fields.get(record["quantity"])
            previous = result.get(field) if field else None
            if isinstance(previous, bool) or not isinstance(previous, int | float):
                continue
            scale = self._scale_of(record["quantity"])
            ended = record["observed"] if record["observed"] is not None else record["target"]
            actual = math.ceil(abs(Decimal(ended) - Decimal(str(previous)) * scale))
            charged = charged_at.get("\x1f".join((record["tenant"], record["quantity"],
                                                   record["resource"])), 0)
            record["actual_movement"] = actual
            if actual > charged:
                record["charged_after"] = actual - charged
                for key, _ in charges:
                    if limit_quantity.get(key.split("\x1f", 1)[0]) == record["quantity"]:
                        self.ledger.debit(key, f"{operation_id}#after", actual - charged, now)

    def settle(self, operation_id: str, ok: bool, result: Any = None,
               now: str | float | None = None) -> list[dict[str, Any]]:
        """Record whether the call ran, and for observed meters where the plant ended up.

        Returns one record per observed resource: the target REMORA let
        through, the value read back, and whether the plant reached it. A
        resource whose value cannot be read back keeps the target (or
        ``unknown`` after a failure); the next change reads the plant anyway.
        """
        settled = self.ledger.settle(operation_id, ok)
        self.ledger.finish(operation_id, ok)
        out: list[dict[str, Any]] = []
        if self.observer is None:
            return out
        scales = {m.quantity: m.scale for meters in self.policy.meters.values()
                  for m in meters if m.observed}
        for value_key, target in settled:
            tenant, quantity, resource = value_key.split("\x1f")
            if quantity not in scales:
                continue
            seen = self._observe(tenant, quantity, resource, scales[quantity])
            record: dict[str, Any] = {"tenant": tenant, "quantity": quantity,
                                      "resource": resource, "target": target,
                                      "observed": None, "reached": None}
            if seen is not None:
                observed_value = int(seen.to_integral_value())
                self.ledger.observe(value_key, observed_value)
                record.update(observed=observed_value, reached=seen == target)
            out.append(record)
        if ok:
            self._account(operation_id, result, out, _epoch(now))
        return out
