# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""LLM-as-proposer arm for semantic authority (QV2-06, SAP v5 §7).

The frozen deterministic extractor in ``bfcl_semantic_bundle`` is safe and
too weak: NEGATIVE_RESULTS.md §39 measured read autonomy at 25/94 on the
sealed C-ext3 track. A development replay on the spent set (2026-10-12,
POST-HOC) puts the losses in two places the gate order cannot reach: tasks
where the extractor grounds no intent at all, and tasks where it grounds the
WRONG resource and so refutes the gold tool. This module lets a model help
with both without giving it any authority.

**A model may propose. It may fill a hole and it may veto. It may never
overrule.** :func:`combine_intents` is the whole rule:

* the deterministic extractor grounded nothing: the proposal is used;
* the proposal is silent or malformed: the deterministic intent is used;
* both grounded the same resource and effect family: the deterministic
  intent is used;
* they disagree: neither is used, and downstream sees UNKNOWN.

So on every task the deterministic extractor grounds, the combined intent is
either that intent or nothing, and ``match_tool_to_intent`` returns either
the deterministic verdict or UNKNOWN. A proposer can turn a refutation into
UNKNOWN (VERIFY under the semantic floor); it cannot turn anything into
SUPPORTED that the extractor refuted or left UNKNOWN on a task it grounded.
New ACCEPTs can only come from tasks the extractor could not ground, and
there the proposal still passes every check goal_match applies: spans quoted
verbatim from the task, a resource from the closed contract lexicon, an
effect keyword that is present and not negated.

Isolation by construction, as SAP v5 §7 requires: the intent prompt receives
the task text and the contract-derived resource lexicon, never the proposed
tool, its arguments, the available tools or anything sealed. The derivation
prompt does see the call's argument values, because a receipt is re-executed
by ``derivation.verify_receipt`` and proves nothing it cannot recompute.

Reproducibility: every completion goes through :class:`RecordReplayProvider`.
A sealed run replays from a cache whose digest, together with the model id
and the prompt hashes, is pinned in the manifest at lock time; a cache miss
in replay mode raises instead of calling a model.

Status: mechanism only. No model or provider is chosen and nothing has been
measured; no number may be cited until a fresh sealed track (C-ext4) runs.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from remora.toolcall.routing.goal_match import EFFECT_VOCABULARY, TaskIntent
from remora.toolcall.routing.tool_contract import READ_EFFECTS

PROPOSER_VERSION = "intent_proposer_v1"

INTENT_PROMPT_TEMPLATE = """\
You extract what a user asks a software agent to do. Answer with one JSON
object and nothing else.

If the task states one request, answer:
{{"effect": E, "action_span": A, "resource": R, "resource_span": S}}
where
- E is one of: {effects}
- A is a short phrase copied exactly from the task that contains the verb
  stating the request
- R is one entry from the resource list below, the thing the request acts on
- S is a phrase copied exactly from the task that contains R

If the task states no request, or several, or none of the resources fits,
answer: {{"effect": null}}

Resources: {resources}

Task:
{task}
"""

DERIVATION_PROMPT_TEMPLATE = """\
A software agent filled the arguments below from a user's task. For each
argument whose value does not appear literally in the task but was computed
from a phrase that does, explain the computation. Answer with one JSON list
and nothing else; use [] when there is nothing to explain.

Each entry: {{"argument": N, "value": V, "transform": T,
"source_span": S, "params": P}}
- T is one of: {transforms}
- S is copied exactly from the task
- P is an object (use {{}} when the transform takes no parameters)

Task:
{task}

Arguments:
{arguments}
"""


def prompt_sha256(template: str) -> str:
    """Hash of a prompt template; pinned in the manifest at lock time."""
    return hashlib.sha256(template.encode("utf-8")).hexdigest()


class CompletionProvider(Protocol):
    """The only thing the proposer needs from a model: text in, text out."""

    model_id: str

    def complete(self, prompt: str) -> str: ...


class ReplayMiss(LookupError):
    """A replay-mode completion was not in the cache. Never a live call."""


class RecordReplayProvider:
    """Cache every completion so a live run can be replayed byte for byte.

    ``mode="record"`` answers from the cache when it can and otherwise calls
    the wrapped provider and appends the answer. ``mode="replay"`` never
    calls anything: a miss raises :class:`ReplayMiss`, because a sealed run
    that silently went live would not be the run that was locked.
    """

    def __init__(self, cache_path: Path, *, model_id: str,
                 mode: str = "replay",
                 provider: CompletionProvider | None = None) -> None:
        if mode not in ("record", "replay"):
            raise ValueError(f"mode must be 'record' or 'replay', got {mode!r}")
        if mode == "record" and provider is None:
            raise ValueError("record mode needs a provider to call on a miss")
        if provider is not None and provider.model_id != model_id:
            raise ValueError(
                f"provider model {provider.model_id!r} is not the pinned "
                f"model {model_id!r}"
            )
        self.model_id = model_id
        self._path = Path(cache_path)
        self._mode = mode
        self._provider = provider
        self._entries: dict[str, str] = {}
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row["model_id"] != model_id:
                    raise ValueError(
                        f"cache {self._path} holds model {row['model_id']!r}, "
                        f"not the pinned {model_id!r}"
                    )
                self._entries[row["key"]] = row["response"]

    def _key(self, prompt: str) -> str:
        return hashlib.sha256(
            (self.model_id + "\0" + prompt).encode("utf-8")
        ).hexdigest()

    def complete(self, prompt: str) -> str:
        key = self._key(prompt)
        if key in self._entries:
            return self._entries[key]
        if self._mode == "replay":
            raise ReplayMiss(f"no cached completion for key {key[:16]}")
        assert self._provider is not None
        response = self._provider.complete(prompt)
        self._entries[key] = response
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(
                {"key": key, "model_id": self.model_id, "response": response},
                sort_keys=True, ensure_ascii=False,
            ) + "\n")
        return response

    def digest(self) -> str:
        """Order-independent digest of the cache content, for the manifest."""
        h = hashlib.sha256()
        for key in sorted(self._entries):
            h.update(key.encode("ascii"))
            h.update(b"\0")
            h.update(self._entries[key].encode("utf-8"))
            h.update(b"\n")
        return h.hexdigest()


_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def _effect_family(effect: str) -> str:
    e = effect.strip().lower()
    return "read" if e in READ_EFFECTS or e == "read" else e


@dataclass(frozen=True)
class IntentProposal:
    """What the proposer returned and why it was or was not usable."""

    intent: TaskIntent | None
    #: ``accepted`` or the first check the proposal failed. Audit only.
    reason: str
    raw: str


def _extract_json(raw: str) -> Any:
    """The first JSON value in *raw*; models wrap answers in prose or fences."""
    start = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0),
                default=-1)
    if start < 0:
        raise ValueError("no JSON value in the completion")
    value, _ = json.JSONDecoder().raw_decode(raw[start:])
    return value


def parse_intent_proposal(raw: str, task: str,
                          lexicon: Iterable[str]) -> IntentProposal:
    """Turn a completion into a TaskIntent, or explain why it cannot be one.

    Every check here is one goal_match would apply anyway; doing them at
    parse time records WHY a proposal was dropped, which the per-cause
    attribution in the next sealed report needs.
    """
    try:
        obj = _extract_json(raw)
    except ValueError:
        return IntentProposal(None, "not_json", raw)
    if not isinstance(obj, dict):
        return IntentProposal(None, "not_an_object", raw)
    effect = obj.get("effect")
    if effect is None:
        return IntentProposal(None, "declined", raw)
    fields = (effect, obj.get("action_span"), obj.get("resource"),
              obj.get("resource_span"))
    if not all(isinstance(v, str) and v.strip() for v in fields):
        return IntentProposal(None, "missing_field", raw)
    effect, action_span, resource, resource_span = (str(v) for v in fields)
    effect = effect.strip().lower()
    if effect not in EFFECT_VOCABULARY:
        return IntentProposal(None, "unknown_effect", raw)
    lex = {_norm(t) for t in lexicon}
    if _norm(resource) not in lex:
        return IntentProposal(None, "resource_not_in_lexicon", raw)
    if _norm(resource) not in _norm(resource_span):
        return IntentProposal(None, "resource_not_in_its_span", raw)
    haystack = _norm(task)
    if _norm(resource_span) not in haystack:
        return IntentProposal(None, "resource_span_not_in_task", raw)
    intent = TaskIntent(
        operation=effect, resource_type=_norm(resource),
        requested_effect=effect,
        source_spans=(resource_span,), action_spans=(action_span,),
        resource_spans=(resource_span,),
        proposed_by=PROPOSER_VERSION,
    )
    # action_grounded_in checks the span is in the task AND carries a
    # non-negated, non-conditional keyword for the effect.
    if not intent.action_grounded_in(task):
        return IntentProposal(None, "action_not_grounded", raw)
    return IntentProposal(intent, "accepted", raw)


def propose_intent(task: str, lexicon: Iterable[str],
                   provider: CompletionProvider) -> IntentProposal:
    """Ask the model for an intent. Sees the task and the lexicon only.

    A provider failure is a silent proposer, never an error the decision
    path has to handle; :class:`ReplayMiss` is the exception, because a
    sealed replay that cannot reproduce itself must stop.
    """
    lex = sorted(set(lexicon))
    prompt = INTENT_PROMPT_TEMPLATE.format(
        effects=", ".join(sorted(EFFECT_VOCABULARY)),
        resources=", ".join(lex), task=task,
    )
    try:
        raw = provider.complete(prompt)
    except ReplayMiss:
        raise
    except Exception:  # noqa: BLE001 — any provider failure is "no proposal"
        return IntentProposal(None, "provider_error", "")
    return parse_intent_proposal(raw, task, lex)


def intents_agree(a: TaskIntent, b: TaskIntent) -> bool:
    """Same resource and same effect family: the two readings coincide."""
    return (_norm(a.resource_type) == _norm(b.resource_type)
            and _effect_family(a.requested_effect)
            == _effect_family(b.requested_effect))


def combine_intents(deterministic: TaskIntent | None,
                    proposed: TaskIntent | None) -> TaskIntent | None:
    """Fill and veto, never overrule. See the module docstring."""
    if deterministic is None:
        return proposed
    if proposed is None or intents_agree(deterministic, proposed):
        return deterministic
    return None


def propose_derivations(task: str, arguments: Mapping[str, Any],
                        provider: CompletionProvider,
                        transforms: Iterable[str]) -> tuple[dict[str, Any], ...]:
    """Ask the model to explain derived argument values as receipts.

    Returns JSON-shaped receipt dicts for ``RoutingEpisode.proposed_derivations``.
    Only shape is checked here; ``derivation.verify_receipt`` re-executes
    each one, and an unverifiable receipt simply leaves its value ungrounded.
    """
    prompt = DERIVATION_PROMPT_TEMPLATE.format(
        transforms=", ".join(sorted(transforms)), task=task,
        arguments=json.dumps(dict(arguments), sort_keys=True, default=str),
    )
    try:
        raw = provider.complete(prompt)
    except ReplayMiss:
        raise
    except Exception:  # noqa: BLE001 — any provider failure is "no receipts"
        return ()
    try:
        items = _extract_json(raw)
    except ValueError:
        return ()
    if not isinstance(items, list):
        return ()
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("argument") not in arguments:
            continue
        if not isinstance(item.get("transform"), str):
            continue
        if not isinstance(item.get("source_span"), str):
            continue
        if "value" not in item:
            continue
        params = item.get("params", {})
        out.append({
            "argument": item["argument"], "value": item["value"],
            "transform": item["transform"],
            "source_span": item["source_span"],
            "params": params if isinstance(params, dict) else {},
        })
    return tuple(out)
