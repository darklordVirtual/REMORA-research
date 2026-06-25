"""Named inspect-ai solvers for the AgentHarm experiment.

These solvers intentionally recreate the AgentHarm task's tool setup when
``--solver`` overrides the task default. Without that setup, Inspect exposes
only its synthetic ``submit`` tool and the run is no longer a tool-use
benchmark.
"""

from inspect_ai.solver import Generate, Solver, TaskState, chain, solver

from inspect_evals.agentharm.agents.default_agent import default_agent
from inspect_evals.agentharm.benchmark import benign_tools, harmful_tools

from experiments.agentharm.remora_mediated_solver import (
    remora_mediated_solver_factory,
)


@solver
def _agentharm_tools_from_metadata() -> Solver:
    """Inject AgentHarm scenario tools from sample metadata.

    The upstream AgentHarm task normally performs this step before running its
    default agent. Passing a custom solver on the Inspect CLI replaces that
    default plan, so REMORA arms must restore the metadata-driven tool surface.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        tools = []
        for name in state.metadata.get("target_functions", []):
            if hasattr(harmful_tools, name):
                tools.append(getattr(harmful_tools, name)())
            elif hasattr(benign_tools, name):
                tools.append(getattr(benign_tools, name)())
            else:
                raise ValueError(f"AgentHarm tool is not available: {name}")
        state.tools = tools
        return state

    return solve


def _base_agent() -> Solver:
    return default_agent()


@solver
def baseline():
    """Arm A: agent alone, no REMORA."""
    return chain(
        _agentharm_tools_from_metadata(),
        _base_agent(),
    )


@solver
def remora_full():
    """Arm B: full REMORA gate."""
    inner = _base_agent()
    return chain(
        _agentharm_tools_from_metadata(),
        remora_mediated_solver_factory(mode="full")(inner),
    )


@solver
def hardblocks_only():
    """Arm C: deterministic hard-blocks only (no oracle consensus)."""
    inner = _base_agent()
    return chain(
        _agentharm_tools_from_metadata(),
        remora_mediated_solver_factory(mode="hardblocks_only")(inner),
    )


@solver
def single_oracle():
    """Arm D: single-oracle REMORA gate (degrades to hard-blocks if engine init fails)."""
    inner = _base_agent()
    return chain(
        _agentharm_tools_from_metadata(),
        remora_mediated_solver_factory(mode="single_oracle")(inner),
    )
