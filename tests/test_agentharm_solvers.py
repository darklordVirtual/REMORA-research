from __future__ import annotations

import importlib
import sys
import types


def _install_fake_inspect_ai(monkeypatch) -> None:
    inspect_ai = types.ModuleType("inspect_ai")
    solver_mod = types.ModuleType("inspect_ai.solver")
    model_mod = types.ModuleType("inspect_ai.model")
    evals_mod = types.ModuleType("inspect_evals")
    agentharm_mod = types.ModuleType("inspect_evals.agentharm")
    agents_mod = types.ModuleType("inspect_evals.agentharm.agents")
    default_agent_mod = types.ModuleType("inspect_evals.agentharm.agents.default_agent")
    benchmark_mod = types.ModuleType("inspect_evals.agentharm.benchmark")
    harmful_tools_mod = types.ModuleType("inspect_evals.agentharm.benchmark.harmful_tools")
    benign_tools_mod = types.ModuleType("inspect_evals.agentharm.benchmark.benign_tools")
    yaml_mod = types.ModuleType("yaml")

    def solver(fn):
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            if not callable(result):
                raise TypeError(f"'{result}' is not declared as an async callable.")
            result.__inspect_solver__ = True
            wrapper.__inspect_solver__ = True
            return result

        wrapper.__inspect_solver__ = True
        return wrapper

    def default_agent():
        async def solve(state, generate):
            return state

        solve.kind = "default_agent"
        return solve

    def chain(*solvers):
        assert solvers

        async def solve(state, generate):
            for step in solvers:
                state = await step(state, generate)
            return state

        solve.kind = "chain"
        solve.steps = solvers
        return solve

    class ChatMessageTool:
        def __init__(self, content, tool_call_id):
            self.content = content
            self.tool_call_id = tool_call_id

    solver_mod.Generate = object
    solver_mod.Solver = object
    solver_mod.TaskState = object
    solver_mod.chain = chain
    solver_mod.solver = solver
    model_mod.ChatMessageTool = ChatMessageTool
    default_agent_mod.default_agent = default_agent
    benchmark_mod.harmful_tools = harmful_tools_mod
    benchmark_mod.benign_tools = benign_tools_mod
    yaml_mod.safe_load = lambda _: {"tools": {}}

    monkeypatch.setitem(sys.modules, "inspect_ai", inspect_ai)
    monkeypatch.setitem(sys.modules, "inspect_ai.solver", solver_mod)
    monkeypatch.setitem(sys.modules, "inspect_ai.model", model_mod)
    monkeypatch.setitem(sys.modules, "inspect_evals", evals_mod)
    monkeypatch.setitem(sys.modules, "inspect_evals.agentharm", agentharm_mod)
    monkeypatch.setitem(sys.modules, "inspect_evals.agentharm.agents", agents_mod)
    monkeypatch.setitem(
        sys.modules,
        "inspect_evals.agentharm.agents.default_agent",
        default_agent_mod,
    )
    monkeypatch.setitem(sys.modules, "inspect_evals.agentharm.benchmark", benchmark_mod)
    monkeypatch.setitem(
        sys.modules,
        "inspect_evals.agentharm.benchmark.harmful_tools",
        harmful_tools_mod,
    )
    monkeypatch.setitem(
        sys.modules,
        "inspect_evals.agentharm.benchmark.benign_tools",
        benign_tools_mod,
    )
    monkeypatch.setitem(sys.modules, "yaml", yaml_mod)


def test_agentharm_solver_arms_are_callable_functions(monkeypatch):
    _install_fake_inspect_ai(monkeypatch)
    sys.modules.pop("experiments.agentharm.remora_mediated_solver", None)
    sys.modules.pop("experiments.agentharm.solvers", None)

    solvers = importlib.import_module("experiments.agentharm.solvers")

    for name in ("baseline", "remora_full", "hardblocks_only", "single_oracle"):
        arm = getattr(solvers, name)
        assert callable(arm), name
        assert getattr(arm, "__inspect_solver__", False), name

        pipeline = arm()
        assert callable(pipeline), name
        assert not isinstance(pipeline, list), name
        assert pipeline.kind == "chain"
        assert len(pipeline.steps) == 2, name
        assert getattr(pipeline.steps[0], "__inspect_solver__", False), name

    assert solvers.baseline().steps[1].kind == "default_agent"
    assert callable(solvers.remora_full().steps[1])
    assert callable(solvers.hardblocks_only().steps[1])
    assert callable(solvers.single_oracle().steps[1])
