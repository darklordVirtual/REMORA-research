# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Declarative argument-validator bindings (§32 follow-up).

§32 measured the UNKNOWN gap: with no closed-world coverage, 50% of corrupted
identifiers were accepted on read-only calls. The system of record could have
answered — ``get_vehicle`` *is* the validator for ``vehicle_id`` — but nothing
said so: resolver matching derived producer names from tool names, and
``get_vehicle`` derives to ``vehicle``, not ``vehicle_id``.

A binding is therefore **declared, never derived**. Like a coverage
declaration, it is a statement a deployment makes and answers for: which tool
validates which argument role, under which tenant, with what attempt budget.
Point lookups need no completeness claim — asking "does V-0113 exist?" is
answerable even when nobody can vouch that a bulk export holds every vehicle —
so validator bindings close the UNKNOWN gap without the closed-world
precondition §31 showed to be fragile.

Two refusals at construction, both §29-shaped:

* a binding cannot disclaim authority — a VERIFY grounded on a lookup the
  deployment itself calls non-authoritative would promise a validation that
  establishes nothing
* every field is mandatory — an unattributed binding is not evidence

Tenant binding is enforced at lookup: a validator declared for one tenant is
invisible to every other, so cross-tenant validation cannot happen by
configuration drift.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


class ValidatorInvalid(ValueError):
    """A validator binding cannot be honoured as written."""


@dataclass(frozen=True)
class ArgumentValidator:
    """One declared binding: this tool validates this argument role."""

    argument_role: str
    tool: str
    #: The parameter of *tool* that receives the value under validation.
    input_argument: str
    tenant: str
    #: Success semantics: the tool confirms the entity exists in the system of
    #: record. The only implemented condition; declaring anything else would
    #: claim a check the code does not perform.
    success_condition: str = "entity_exists"
    authoritative: bool = True
    max_attempts: int = 1

    def __post_init__(self) -> None:
        for field_name in ("argument_role", "tool", "input_argument", "tenant"):
            if not str(getattr(self, field_name)).strip():
                raise ValidatorInvalid(f"{field_name} must not be empty")
        if not self.authoritative:
            raise ValidatorInvalid(
                "a validator binding must be authoritative; grounding a VERIFY "
                "on a non-authoritative lookup would promise a validation that "
                "establishes nothing"
            )
        if self.success_condition != "entity_exists":
            raise ValidatorInvalid(
                f"success_condition {self.success_condition!r} is not "
                "implemented; declaring it would claim a check the code does "
                "not perform"
            )
        if self.max_attempts < 1:
            raise ValidatorInvalid("max_attempts must be at least 1")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "argument_role": self.argument_role,
            "tool": self.tool,
            "input_argument": self.input_argument,
            "tenant": self.tenant,
            "success_condition": self.success_condition,
            "authoritative": self.authoritative,
            "max_attempts": self.max_attempts,
        }

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> "ArgumentValidator":
        return cls(
            argument_role=d["argument_role"],
            tool=d["tool"],
            input_argument=d["input_argument"],
            tenant=d["tenant"],
            success_condition=d.get("success_condition", "entity_exists"),
            authoritative=bool(d.get("authoritative", True)),
            max_attempts=int(d.get("max_attempts", 1)),
        )


@dataclass(frozen=True)
class ValidatorRegistry:
    """The validator bindings a deployment declares."""

    validators: tuple[ArgumentValidator, ...] = ()
    #: Set by :meth:`scoped`. A registry with a scope tenant answers
    #: tenant-free lookups (:meth:`tools_for`) for exactly that tenant.
    scope_tenant: str | None = None

    def for_argument(
        self, argument_role: str, *, tenant: str
    ) -> ArgumentValidator | None:
        for validator in self.validators:
            if validator.argument_role == argument_role and validator.tenant == tenant:
                return validator
        return None

    def scoped(self, tenant: str) -> "ValidatorRegistry":
        """The registry as one tenant sees it: foreign bindings do not exist."""
        return ValidatorRegistry(
            tuple(v for v in self.validators if v.tenant == tenant),
            scope_tenant=tenant,
        )

    def tools_for(self, argument_roles: Sequence[str]) -> tuple[str, ...]:
        """Validator tools for *argument_roles* under the scope tenant.

        Refuses on an unscoped registry: a tenant-free lookup against all
        tenants' bindings is exactly the configuration drift tenant binding
        exists to prevent.
        """
        if self.scope_tenant is None:
            raise ValidatorInvalid(
                "tools_for requires a tenant-scoped registry; call scoped(tenant)"
            )
        out: list[str] = []
        for role in argument_roles:
            validator = self.for_argument(role, tenant=self.scope_tenant)
            if validator is not None and validator.tool not in out:
                out.append(validator.tool)
        return tuple(out)

    def to_json_dict(self) -> dict[str, Any]:
        return {"validators": [v.to_json_dict() for v in self.validators]}

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> "ValidatorRegistry":
        return cls(
            tuple(ArgumentValidator.from_json_dict(v) for v in d["validators"])
        )
