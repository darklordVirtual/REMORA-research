# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Frozen deterministic semantic bundle for the BFCL tracks (SAP v5 §6–§7).

Contract authoring and intent extraction as PURE FUNCTIONS of tool metadata
and task text respectively. The freeze property is structural: the contract
author reads ONLY tool names (and nothing else — not schemas beyond what the
registry carries, not questions, not gold answers, not predictions); the
intent extractor reads ONLY the user task plus a resource lexicon derived
from the contract bundle. Neither can peek by construction. The file's
SHA-256 is recorded in the C-ext3 manifest at lock time; any edit after lock
invalidates the run.

Disclosed limitation (SAP v5 §12): the heuristic grammar below was designed
while the SPENT C-ext2 material was visible during the post-hoc development
reanalysis. The C-ext3 rows themselves are selected by a fresh seed after
this file is frozen and are unseen by everyone.
"""
from __future__ import annotations

import re

from remora.toolcall.routing.goal_match import EFFECT_VOCABULARY, TaskIntent
from remora.toolcall.routing.tool_contract import (
    ToolContract,
    ToolContractRegistry,
)

BUNDLE_VERSION = "bfcl_semantic_bundle_v1"

_READ_VERBS = {"get", "find", "list", "search", "show", "lookup", "query",
               "retrieve", "check", "view"}
_EFFECT_VERBS = {
    "buy": "create", "book": "create", "reserve": "create", "add": "create",
    "create": "create", "schedule": "create", "play": "create",
    "order": "create", "transfer": "update", "send": "create",
    "update": "update", "change": "update", "set": "update",
    "execute": "update", "control": "update",
    "cancel": "cancel", "delete": "delete", "remove": "delete",
}


def _tokens(name: str) -> list[str]:
    """Snake, camel and dotted tool names normalize to lowercase tokens."""
    name = name.split(".")[-1]
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return [t for t in re.split(r"[_\W]+", name.lower()) if t]


def capability_of(tool: str) -> str:
    """Domain prefix convention: ``Buses_3_FindBus`` → ``buses``."""
    head = re.split(r"[._]", tool)[0]
    return re.sub(r"\d+$", "", head).lower() or "general"


def author_contract(tool: str) -> ToolContract:
    """Deterministic contract from the tool NAME alone.

    Unrecognized verbs are declared as mutating updates on purpose: an
    unclassifiable tool must never be blessed as a harmless read.
    """
    toks = _tokens(tool)
    first = toks[0] if toks else ""
    last = toks[-1] if toks else ""
    if first in _READ_VERBS:
        effect, mutation, resource_toks = "read", False, toks[1:]
    elif first in _EFFECT_VERBS:
        effect, mutation, resource_toks = _EFFECT_VERBS[first], True, toks[1:]
    elif last in _READ_VERBS:
        # resource_verb naming (``calendar_event_list``): verb at the end.
        effect, mutation, resource_toks = "read", False, toks[:-1]
    elif last in _EFFECT_VERBS:
        effect, mutation, resource_toks = _EFFECT_VERBS[last], True, toks[:-1]
    else:
        effect, mutation, resource_toks = "update", True, toks
    resource = " ".join(resource_toks) or capability_of(tool)
    # Generous aliases: every contiguous token n-gram of the resource, so an
    # intent that grounded "bus" still matches a "bus ticket" tool and vice
    # versa — the effect and capability axes carry the discrimination.
    aliases: list[str] = []
    for i in range(len(resource_toks)):
        for j in range(i + 1, len(resource_toks) + 1):
            gram = " ".join(resource_toks[i:j])
            if gram and gram != resource:
                aliases.append(gram)
    # Naive number variants so "provider" grounds a "providers" tool: the
    # last word of the resource and of every alias gains its singular/plural
    # counterpart.
    def _number_variants(phrase: str) -> list[str]:
        head, _, tail = phrase.rpartition(" ")
        out = []
        if tail.endswith("s") and len(tail) > 3:
            out.append((head + " " + tail[:-1]).strip())
        else:
            out.append((head + " " + tail + "s").strip())
        return out
    for phrase in [resource, *aliases]:
        aliases.extend(v for v in _number_variants(phrase)
                       if v and v != resource)
    return ToolContract(
        tool=tool, capability=capability_of(tool), effect=effect,
        resource_type=resource, mutation=mutation, argument_roles={},
        resource_aliases=tuple(dict.fromkeys(aliases)),
    )


def author_bundle(tools: list[str]) -> ToolContractRegistry:
    return ToolContractRegistry(
        contracts=[author_contract(t) for t in sorted(set(tools))]
    )


def resource_lexicon(bundle: ToolContractRegistry, tools: list[str]) -> set[str]:
    """Resource vocabulary derived from the CONTRACTS, never from tasks."""
    lex: set[str] = set()
    for tool in tools:
        contract = bundle.get(tool)
        if contract is None:
            continue
        lex.add(contract.resource_type)
        lex.update(_tokens(tool)[1:])
    _GENERIC = {"latest", "current", "available", "recent", "new", "all",
                "info", "information", "data", "list", "details", "history",
                "state", "status", "api", "get", "value", "values"}
    return {t for t in lex if len(t) > 2 and t not in _GENERIC}


def full_resource_set(bundle: ToolContractRegistry,
                      tools: list[str]) -> frozenset[str]:
    """The complete contract resource strings, for match ranking."""
    return frozenset(
        c.resource_type for c in (bundle.get(t) for t in tools) if c
    )


def extract_intent(task: str, lexicon: set[str],
                   full_resources: frozenset[str] = frozenset()) -> TaskIntent | None:
    """Deterministic extractor: user task text ONLY.

    Finds an unambiguous effect keyword (EFFECT_VOCABULARY) and a resource
    token from the contract-derived lexicon appearing verbatim in the task.
    Returns None when either cannot be grounded — an ungrounded intent must
    yield UNKNOWN downstream, never a guess.
    """
    if not task:
        return None
    lowered = task.lower()

    # Effect: whole-word matches only, canonicalized to effect families.
    # Multiple DISTINCT non-read families in one task is ambiguous — return
    # None so downstream stays UNKNOWN rather than guessing.
    _READ_FAMILY = {"read", "retrieve", "search", "list", "get", "query",
                    "lookup"}
    hits: dict[str, tuple[int, str]] = {}
    for eff, keywords in EFFECT_VOCABULARY.items():
        family = "read" if eff in _READ_FAMILY else eff
        for kw in keywords:
            m = re.search(rf"\b{re.escape(kw)}\b", lowered)
            if m and (family not in hits or m.start() < hits[family][0]):
                hits[family] = (m.start(), task[m.start():m.end()])
    if not hits:
        return None
    non_read = {f: v for f, v in hits.items() if f != "read"}
    if len(non_read) > 1:
        return None  # two distinct mutating requests; UNKNOWN downstream
    _WEAK_READ = {"need", "want", "provide", "tell", "give", "review",
                  "know", "access"}
    read_hit = hits.get("read")
    read_is_weak = bool(read_hit) and read_hit[1].lower() in _WEAK_READ
    if non_read and (read_hit is None or read_is_weak):
        # An explicit mutation keyword always beats weak read cues:
        # "I need it cancelled" is a cancel, never a read.
        effect, (_, span) = next(iter(non_read.items()))
    elif non_read:
        # Strong read verb vs mutation keyword: the user's leading verb
        # states the request; a later keyword is usually a parameter
        # modifier ("… page size set to 50" is still a read). Earliest
        # occurrence wins; ties go to the mutation (safety first).
        effect, (_, span) = min(
            hits.items(), key=lambda kv: (kv[1][0], kv[0] == "read")
        )
    else:
        effect, (_, span) = "read", read_hit

    # Resource: whole-word lexicon matches, preferring full contract
    # resources over bare name tokens, then longer over shorter, then the
    # match nearest the action keyword (the requested object usually sits
    # next to the requesting verb).
    action_pos = lowered.find(span.lower())

    def _rank(tok: str) -> tuple:
        return (tok in full_resources, len(tok),
                -abs(lowered.find(tok) - action_pos))

    matches = sorted(
        (tok for tok in lexicon
         if re.search(rf"\b{re.escape(tok)}\b", lowered)),
        key=_rank, reverse=True,
    )
    if not matches:
        return None
    resource = matches[0]
    # Strip leading generic modifiers so "current weather" grounds a
    # "weather" tool: the modifier is task phrasing, not the resource.
    _MODIFIERS = {"current", "latest", "available", "recent", "new", "my",
                  "the", "all"}
    parts = resource.split()
    while len(parts) > 1 and parts[0] in _MODIFIERS:
        parts = parts[1:]
    resource = " ".join(parts)
    r_idx = lowered.find(resource)
    r_span = task[r_idx:r_idx + len(resource)]
    return TaskIntent(
        operation=effect, resource_type=resource, requested_effect=effect,
        source_spans=(r_span,), action_spans=(span,), resource_spans=(r_span,),
        proposed_by=BUNDLE_VERSION,
    )
