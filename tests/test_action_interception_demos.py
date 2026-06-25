from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_example(name: str) -> ModuleType:
    path = ROOT / "examples" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_openai_tool_calling_demo_dispatches_only_accepts() -> None:
    demo = _load_example("openai_tool_calling")

    result = demo.run_demo()
    outputs = result["outputs"]

    assert result["executed"] == ["search_knowledge_base"]
    assert _outcome_for(outputs, "search_knowledge_base") == ("accept", True)
    assert _outcome_for(outputs, "create_support_ticket") == ("verify", False)
    assert _outcome_for(outputs, "delete_account") == ("escalate", False)


def test_langgraph_demo_dispatches_only_accepts() -> None:
    demo = _load_example("langgraph_integration")

    outputs, executed = demo.run_demo()

    assert executed == ["search_docs"]
    assert _outcome_for(outputs, "search_docs") == ("accept", True)
    assert _outcome_for(outputs, "send_email") == ("verify", False)
    assert _outcome_for(outputs, "delete_table") == ("escalate", False)


def _outcome_for(outputs: list[dict[str, object]], tool: str) -> tuple[object, object]:
    for item in outputs:
        if item["tool"] == tool:
            return item["outcome"], item["executed"]
    raise AssertionError(f"Missing tool result for {tool}")
