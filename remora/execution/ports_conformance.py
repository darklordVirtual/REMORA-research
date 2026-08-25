# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Static proof that the production classes satisfy the execution ports.

The ports in :mod:`remora.execution.ports` are structural, so nothing forces
``TenantAuditChain`` or ``EnforcementGate`` to keep matching them -- a renamed
method would type-check everywhere except at the one wiring site in
``servers/``, which is outside this package's fastest feedback loop. This
module turns conformance into a gate property: it contains no runtime logic,
only annotated assignments that ``mypy remora servers`` (the CI quality gate)
must prove. If a concrete class drifts from a port, the gate fails naming the
class and the member, before any test runs.

Deliberately not a test file: tests are not in the mypy gate's scope, and a
runtime ``isinstance`` against a Protocol checks attribute presence, not
signatures. The assignments below check the signatures.

``TYPE_CHECKING``-only, so importing this module at runtime costs nothing and
imports nothing heavy.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.enforcement.gate import EnforcementGate
    from remora.enforcement.lease import GovernedToolDispatcher
    from remora.enforcement.outbox import (ExecutionOutbox,
                                           PostgresExecutionOutbox,
                                           SQLiteExecutionOutbox)
    from remora.enforcement.token import PolicyDecisionToken
    from remora.execution.ports import (AuditChainPort, DispatchOutboxPort,
                                        EnforcementGatePort,
                                        PolicyDecisionTokenPort,
                                        ReviewQueuePort, ToolDispatcherPort)
    from remora.governance.review_queue import ReviewQueue
    from remora.governance.tenant_chain import (PostgresTenantChain,
                                                SQLiteTenantChain,
                                                TenantAuditChain)

    def _conforms(
        in_memory_chain: TenantAuditChain,
        sqlite_chain: SQLiteTenantChain,
        postgres_chain: PostgresTenantChain,
        gate: EnforcementGate,
        token: PolicyDecisionToken,
        dispatcher: GovernedToolDispatcher,
        outbox: ExecutionOutbox,
        sqlite_outbox: SQLiteExecutionOutbox,
        postgres_outbox: PostgresExecutionOutbox,
        queue: ReviewQueue,
    ) -> None:
        """Every assignment below is a claim the type checker must prove."""
        _chain1: AuditChainPort = in_memory_chain
        _chain2: AuditChainPort = sqlite_chain
        _chain3: AuditChainPort = postgres_chain
        _gate: EnforcementGatePort = gate
        _token: PolicyDecisionTokenPort = token
        _dispatcher: ToolDispatcherPort = dispatcher
        _outbox1: DispatchOutboxPort = outbox
        _outbox2: DispatchOutboxPort = sqlite_outbox
        _outbox3: DispatchOutboxPort = postgres_outbox
        _queue: ReviewQueuePort = queue
