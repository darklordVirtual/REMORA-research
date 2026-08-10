# SPDX-License-Identifier: BUSL-1.1
"""Governed Programmatic Tool Calling (GPTC) — RF-11.

This package implements the PTC planning layer described in:

    Patel, Sen, Lumer & Subbiah (2025). "The Bitter Lesson of Tool Calling."
    arXiv:2608.06370. PricewaterhouseCoopers Commercial Technology and
    Innovation Office.

The architecture is:

    LLM
     │
     ▼
    Python tool program   ← UNTRUSTED; sandbox sees no network/credentials
     │
     ▼
    CallGraphExtractor    ← pure AST; never eval/exec untrusted code
     │
     ▼
    ProposedCall list     ← data only, no authority
     │
     ▼
    GovernedBatchExecutor ← submits each call to REMORA assess/dispatch
     │
     ▼
    DecisionEnvelope per call + results

The critical boundary: Python is computation; REMORA owns authority.
Stubs MUST NOT touch real APIs. The only exit from the sandbox is the
REMORA broker interface.

Security note: the call graph extractor is purely static (AST). It never
executes untrusted programs. Execution happens only for calls that have
passed REMORA governance and received an individual signed grant.
"""
from remora.toolcall.ptc.stub_generator import (
    PythonStub,
    StubGenerationError,
    generate_stubs,
    render_stub_module,
)
from remora.toolcall.ptc.call_graph import (
    CallGraphError,
    ProposedCall,
    extract_call_graph,
)
from remora.toolcall.ptc.governed_batch import (
    BatchOutcome,
    CallResult,
    GovernedBatchExecutor,
)

__all__ = [
    # stub generator
    "PythonStub",
    "StubGenerationError",
    "generate_stubs",
    "render_stub_module",
    # call graph
    "CallGraphError",
    "ProposedCall",
    "extract_call_graph",
    # governed execution
    "BatchOutcome",
    "CallResult",
    "GovernedBatchExecutor",
]
