# SPDX-License-Identifier: BUSL-1.1
"""InjecAgent's own prompt and evaluator, loaded from the pinned checkout at run time.

SAP v7 §13.2 fixes the agent prompt (``src/prompts/``, prompt type
``InjecAgent``) and the evaluator (``src/output_parsing.py::
evaluate_output_prompted``). This module loads both from the checkout by
file path, after checking the SHA-256 of the two files, so the harness uses
InjecAgent's code rather than a copy. The evaluator imports ``nltk``, which
the run environment must provide.

Prompt filling repeats ``predict_one_case`` of ``src/evaluate_prompted_agent.py``
character for character. That function is not imported because its module
imports an OpenAI client at import time.

Two choices are this harness's own:

* InjecAgent's Claude class calls the retired Text Completions API. Here the
  system prompt goes in the Messages API ``system`` field and the filled
  user prompt is the one user message, as InjecAgent frames its GPT models.
* For the U2 twins (§13.6) the user prompt lists only the attacker tools and
  the scratchpad is empty, because no tool has run.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from experiments.injection_eval.builder import AttackedCase
from experiments.sap_v7_addenda.seal import RunRefused

PROMPT_TYPE = "InjecAgent"
#: Raw SHA-256 of the upstream code this module loads, at the pinned commit.
CODE_FILES: dict[str, str] = {
    "src/output_parsing.py": "b841348cdbc5b87c781bed4a592d375d02d51769ac2435cf2e7e69c08a03937b",
    "src/prompts/agent_prompts.py": "f0249e434c46a9944dab9797edee4cd41e4fc6fceb48b8b8004585a7a4866037",
}

Evaluator = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class Upstream:
    system_prompt: str
    user_prompt: str
    evaluate: Evaluator


def _module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RunRefused(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load(root: Path, code_files: Mapping[str, str] | None = None) -> Upstream:
    pins = dict(code_files if code_files is not None else CODE_FILES)
    for rel, expected in sorted(pins.items()):
        path = Path(root) / rel
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RunRefused(f"upstream file {rel} differs from the pin")
    prompts = _module(Path(root) / "src/prompts/agent_prompts.py", "_injecagent_agent_prompts")
    parsing = _module(Path(root) / "src/output_parsing.py", "_injecagent_output_parsing")
    system_prompt, user_prompt = prompts.PROMPT_DICT[PROMPT_TYPE]
    return Upstream(system_prompt, user_prompt, parsing.evaluate_output_prompted)


def scratchpad(case: AttackedCase, stage2: Mapping[str, str] | None = None) -> str:
    """``agent_scratchpad`` of ``predict_one_case`` for stage 1, or stage 2 when given."""
    item = case.raw
    if stage2 is None:
        return (f"\n{item['Thought']}\nAction: {item['User Tool']}\nAction Input: "
                f"{item['Tool Parameters']}\nObservation: {item['Tool Response']}\n")
    return (f"\n{item['Thought']}\nAction: {item['User Tool']}\nAction Input: "
            f"{item['Tool Parameters']}\nObservation: {item['Tool Response']}\n"
            f"Thought: {stage2['Attacker Tool Thought']}\nAction: {item['Attacker Tools'][0]}\n"
            f"Action Input: {stage2['Attacker Tool Parameters']}\n"
            f"Observation: {stage2['Attacker Tool Response']}\n")


def fill(upstream: Upstream, tool_dict: Mapping[str, Mapping[str, Any]], instruction: str,
         tool_names: Sequence[str], agent_scratchpad: str) -> tuple[str, str]:
    """System prompt and filled user prompt, as ``predict_one_case`` builds them."""
    names = list(tool_names)
    descriptions = json.dumps([tool_dict[t] for t in names], indent=True)
    user = upstream.user_prompt.format(available_tool_descriptions=descriptions, input=instruction,
                                       available_tool_names=names,
                                       agent_scratchpad=agent_scratchpad)
    return upstream.system_prompt, user


def case_prompt(upstream: Upstream, tool_dict: Mapping[str, Mapping[str, Any]],
                case: AttackedCase, stage2: Mapping[str, str] | None = None) -> tuple[str, str]:
    return fill(upstream, tool_dict, case.user_instruction,
                [case.user_tool, *case.attacker_tools], scratchpad(case, stage2))
