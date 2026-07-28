# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tenant-isolation invariant for a shared, multi-tenant assurance service.

In a service that mirrors many customers' registers, tenant A must never read
tenant B's rows, and per-tenant append-only ledgers must never interleave. This
models exactly that with a row-scoped store and one hash chain per tenant. It is
a MODEL of the invariant: no authn, transport or persistence. It proves the
scoping/chaining logic is sound; a deployment must still enforce the same
boundary at the auth and storage layers.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


class CrossTenantError(KeyError):
    """A read/write named a tenant that does not own the row."""


def _canon(row: dict) -> str:
    return "|".join(f"{k}={row[k]}" for k in sorted(row))


@dataclass
class TenantStore:
    """Key->value store scoped by tenant, plus a per-tenant hash chain."""

    _rows: dict[tuple[str, str], str] = field(default_factory=dict)
    _heads: dict[str, str] = field(default_factory=dict)

    def put(self, tenant: str, key: str, value: str) -> str:
        self._rows[(tenant, key)] = value
        prev = self._heads.get(tenant, "genesis")
        # Bind the tenant into the chain entry so two tenants with identical
        # write sequences still get distinct heads — the ledger is per-tenant.
        head = hashlib.sha256(
            _canon({"tenant": tenant, "key": key, "value": value, "prev": prev}).encode()
        ).hexdigest()
        self._heads[tenant] = head
        return head

    def get(self, tenant: str, key: str) -> str:
        try:
            return self._rows[(tenant, key)]
        except KeyError:
            raise CrossTenantError(f"tenant {tenant!r} has no row {key!r}") from None

    def head(self, tenant: str) -> str:
        return self._heads.get(tenant, "genesis")

    def can_read(self, tenant: str, key: str) -> bool:
        return (tenant, key) in self._rows


@dataclass
class IsolationReport:
    n_tenants: int
    n_isolation_checks: int
    cross_tenant_leaks: int
    n_chain_forks: int


def run_isolation_battery(
    n_tenants: int = 5, keys_per_tenant: int = 4
) -> IsolationReport:
    store = TenantStore()
    tenants = [f"tenant-{i}" for i in range(n_tenants)]
    # Tenant-UNIQUE keys: tenant-i owns "tenant-i/k{j}". This is what makes the
    # leak check real — a shared key set (the pre-2026-07-28 version) let every
    # read hit under the reader's own scope, so cross_tenant_leaks could never
    # be non-zero and CrossTenantError was never exercised (issue #56).
    def owned_keys(t: str) -> list[str]:
        return [f"{t}/k{j}" for j in range(keys_per_tenant)]

    for t in tenants:
        for k in owned_keys(t):
            store.put(t, k, f"{t}:{k}:secret")

    checks = leaks = forks = 0
    # The adversarial check: each tenant tries to read every OTHER tenant's
    # keys UNDER ITS OWN scope. A correct scoped store must refuse every such
    # read (CrossTenantError / can_read == False); any success is a leak.
    for owner in tenants:
        for other in tenants:
            if other == owner:
                continue
            for k in owned_keys(other):
                checks += 1
                if store.can_read(owner, k):
                    leaks += 1
                    continue
                try:
                    store.get(owner, k)
                    leaks += 1  # returned another tenant's row under owner scope
                except CrossTenantError:
                    pass  # correctly refused

    for t in tenants:
        solo = TenantStore()
        for k in owned_keys(t):
            solo.put(t, k, f"{t}:{k}:secret")
        checks += 1
        if solo.head(t) != store.head(t):
            forks += 1

    return IsolationReport(len(tenants), checks, leaks, forks)
