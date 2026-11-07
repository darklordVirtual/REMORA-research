# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""AgentHarm harness: REMORA decides each tool call before the tool runs.

Runs Inspect's real tool loop with its mock model, so no network, key or
dataset is needed. The model proposes calls; the test checks which tool
bodies actually executed and what the model was told. This verifies the
PreToolUse path INTERCEPTION_NOTES.md required before the harness may be
described as tool-call interception. It is not an AgentHarm result.
"""
from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import Task, eval as inspect_eval  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.model import ChatMessageTool, ModelOutput, get_model  # noqa: E402
from inspect_ai.solver import chain, generate, use_tools  # noqa: E402
from inspect_ai.tool import tool  # noqa: E402

import experiments.agentharm.remora_mediated_solver as rms  # noqa: E402

EXECUTED: list[str] = []


@tool
def send_note():
    async def execute(text: str) -> str:
        """Send a note.

        Args:
            text: The note text.
        """
        EXECUTED.append(text)
        return f"sent: {text}"

    return execute


@tool
def delete_file():
    async def execute(path: str) -> str:
        """Delete a file.

        Args:
            path: File path.
        """
        EXECUTED.append(f"deleted {path}")
        return "deleted"

    return execute


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    EXECUTED.clear()
    monkeypatch.setattr(rms, "ENVELOPE_LOG", tmp_path / "envelopes.jsonl")
    yield


def _run(tools, calls, mode="hardblocks_only"):
    outputs = [ModelOutput.for_tool_call("mockllm/model", name, args)
               for name, args in calls]
    outputs.append(ModelOutput.from_content("mockllm/model", "done"))
    model = get_model("mockllm/model", custom_outputs=outputs)
    task = Task(
        dataset=[Sample(input="do the task", metadata={})],
        solver=chain(use_tools(tools),
                     rms.remora_mediated_solver_factory(mode=mode)(
                         generate(tool_calls="loop"))),
    )
    [log] = inspect_eval(task, model=model, display="none",
                         log_dir=str(rms.ENVELOPE_LOG.parent / "logs"))
    assert log.status == "success", log.error
    [sample] = log.samples
    return sample


def _tool_results(sample) -> list[str]:
    return [m.text for m in sample.messages if isinstance(m, ChatMessageTool)]


def test_an_accepted_call_executes_with_the_models_arguments() -> None:
    sample = _run([send_note()], [("send_note", {"text": "hello"})])
    assert EXECUTED == ["hello"]
    [decision] = sample.metadata[rms.TOOL_DECISIONS_KEY]
    assert decision["tool"] == "send_note"
    assert decision["outcome"] == "ACCEPT" and decision["executed"] is True
    assert _tool_results(sample) == ["sent: hello"]


def test_a_hard_blocked_call_never_reaches_the_tool_body() -> None:
    # Block 2: credential keywords in the real arguments. The tool-level
    # pre-assessment has no arguments, so only call-level gating sees this.
    sample = _run([send_note()], [("send_note", {"text": "the password is hunter2"}),
                                  ("send_note", {"text": "hello"})])
    assert EXECUTED == ["hello"]
    decisions = sample.metadata[rms.TOOL_DECISIONS_KEY]
    assert [(d["outcome"], d["executed"]) for d in decisions] == [
        ("ESCALATE", False), ("ACCEPT", True)]
    assert _tool_results(sample)[0] == rms.refusal_text("send_note", "ESCALATE")


def test_a_critical_delete_is_refused_by_tool_class() -> None:
    sample = _run([delete_file()], [("delete_file", {"path": "/tmp/x"})])
    assert EXECUTED == []
    [decision] = sample.metadata[rms.TOOL_DECISIONS_KEY]
    assert decision["outcome"] == "ESCALATE" and decision["executed"] is False


@pytest.mark.parametrize("outcome", ["VERIFY", "ABSTAIN", "ESCALATE", "garbage"])
def test_only_accept_executes(monkeypatch, outcome) -> None:
    monkeypatch.setattr(rms.RemoraGate, "assess",
                        lambda self, n, a, s="": {"gate": {"outcome": outcome}})
    sample = _run([send_note()], [("send_note", {"text": "hello"})])
    assert EXECUTED == []
    [decision] = sample.metadata[rms.TOOL_DECISIONS_KEY]
    assert decision["executed"] is False


def test_a_gate_exception_is_recorded_and_not_executed(monkeypatch) -> None:
    def boom(self, n, a, s=""):
        if a:  # only the call-level assessment carries arguments
            raise RuntimeError("gate down")
        return {"gate": {"outcome": "ACCEPT"}}

    monkeypatch.setattr(rms.RemoraGate, "assess", boom)
    sample = _run([send_note()], [("send_note", {"text": "hello"})])
    assert EXECUTED == []
    [decision] = sample.metadata[rms.TOOL_DECISIONS_KEY]
    assert decision["outcome"] == "VERIFY" and decision["executed"] is False


def test_the_model_sees_the_same_tool_schema_as_the_baseline() -> None:
    from inspect_ai.tool import ToolDef

    gate = rms.RemoraGate(mode="hardblocks_only")
    original = ToolDef(send_note())
    wrapped = ToolDef(rms.gate_tool(send_note(), gate, "s0", []))
    assert wrapped.name == original.name
    assert wrapped.description == original.description
    assert wrapped.parameters == original.parameters


def test_a_real_agentharm_tool_is_wrapped_without_changing_its_schema() -> None:
    harmful_tools = pytest.importorskip("inspect_evals.agentharm.benchmark.harmful_tools")
    from inspect_ai.tool import ToolDef

    gate = rms.RemoraGate(mode="hardblocks_only")
    original = ToolDef(harmful_tools.add_hidden_malware())
    wrapped = ToolDef(rms.gate_tool(harmful_tools.add_hidden_malware(), gate, "s0", []))
    assert (wrapped.name, wrapped.description, wrapped.parameters) == (
        original.name, original.description, original.parameters)
