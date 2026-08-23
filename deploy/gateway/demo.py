# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Live demonstration of the governed MCP gateway.

Runs the whole story against the deployed gateway, in order: autonomous
grounded reads, the human approval loop, the refusals that make the approvals
mean something, effect verification, and the one-time grant. Every claim on
screen is the gateway's own answer, fetched live — nothing is mocked.

Configuration (environment):
    REMORA_DEMO_URL          gateway base URL
    REMORA_DEMO_ACCESS_ID    Cloudflare Access service token id
    REMORA_DEMO_ACCESS_SECRET
    REMORA_DEMO_APPROVER     bearer token holding the approver role

Usage:
    python deploy/gateway/demo.py            # full run
    python deploy/gateway/demo.py --fast     # skip the retry/settle waits
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.getenv("REMORA_DEMO_URL",
                 "https://remora-mcp-gateway.razorsharp.workers.dev")
BUSINESS = "urn:exeqta:tenant:luftfiber:business"
SCRATCH = "urn:exeqta:tenant:luftfiber:remora-evaltest"
INTENTS = "urn:remora:intents"
READ_TASK = "task:survey-business-graph"
WRITE_TASK = "task:record-customer-status"

FAST = "--fast" in sys.argv
_rid = [0]

# A demonstration that crashes on a Windows console is not a demonstration.
# cp1252 cannot print the rules and arrows below; UTF-8 can, everywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _headers() -> dict[str, str]:
    cid = os.getenv("REMORA_DEMO_ACCESS_ID", "").strip()
    secret = os.getenv("REMORA_DEMO_ACCESS_SECRET", "").strip()
    if not cid or not secret:
        sys.exit("REMORA_DEMO_ACCESS_ID / REMORA_DEMO_ACCESS_SECRET are not "
                 "set. The gateway sits behind Cloudflare Access; that is "
                 "part of the demonstration, not an obstacle to it.")
    return {"User-Agent": "remora-demo/1.0",
            "Content-Type": "application/json",
            "CF-Access-Client-Id": cid,
            "CF-Access-Client-Secret": secret}


def call(name: str, args: dict) -> tuple[dict, float]:
    _rid[0] += 1
    body = {"jsonrpc": "2.0", "id": _rid[0], "method": "tools/call",
            "params": {"name": name, "arguments": args}}
    req = urllib.request.Request(BASE + "/mcp",
                                 data=json.dumps(body).encode(),
                                 headers=_headers())
    attempts = 1 if FAST else 10
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                out = json.loads(resp.read())
            elapsed = (time.perf_counter() - started) * 1000
            return json.loads(out["result"]["content"][0]["text"]), elapsed
        except urllib.error.HTTPError as exc:
            if exc.code in (500, 503) and attempt + 1 < attempts:
                time.sleep(15)   # container may be waking
                continue
            raise
    raise SystemExit("gateway did not settle")


def approve(item_id: str) -> int:
    token = os.getenv("REMORA_DEMO_APPROVER", "").strip()
    if not token:
        sys.exit("REMORA_DEMO_APPROVER is not set — the approval half of the "
                 "demonstration needs the approver role.")
    headers = dict(_headers())
    headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        BASE + "/approve",
        data=json.dumps({"item_id": item_id,
                         "approval_ttl_seconds": 900}).encode(),
        headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=150) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


# ── presentation ────────────────────────────────────────────────────────────

def head(title: str) -> None:
    print(f"\n{'─' * 72}\n  {title}\n{'─' * 72}")


def show(label: str, payload: dict, ms: float, *keys: str) -> None:
    decision = payload.get("decision") or payload.get("error") or ""
    status = payload.get("status") or ""
    print(f"\n  {label}")
    line = " / ".join(x for x in (decision, status) if x) or "?"
    print(f"    -> {line}   ({ms:.0f} ms)")
    reasons = payload.get("reasons")
    if reasons:
        print(f"    reasons: {', '.join(reasons)}")
    for key in keys:
        if payload.get(key) is not None:
            value = payload[key]
            text = json.dumps(value, ensure_ascii=False) \
                if isinstance(value, (dict, list)) else str(value)
            print(f"    {key}: {text[:120]}")


def expect(condition: bool, what: str) -> None:
    mark = "ok" if condition else "DEMO BROKE"
    print(f"    [{mark}] {what}")
    if not condition:
        sys.exit(1)


def main() -> None:
    print("REMORA governed MCP gateway — live demonstration")
    print(f"target: {BASE}")

    # ── 0. the boundary itself ───────────────────────────────────────────
    head("0 · The edge refuses before REMORA is ever reached")
    bare = {k: v for k, v in _headers().items()
            if not k.startswith("CF-Access")}
    req = urllib.request.Request(
        BASE + "/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": 1,
                         "method": "tools/list"}).encode(),
        headers=bare)
    try:
        urllib.request.urlopen(req, timeout=60)
        code = 200
    except urllib.error.HTTPError as exc:
        code = exc.code
    print(f"\n  request without the Access service token → HTTP {code}")
    expect(code == 403, "unauthenticated requests never reach the gateway")

    # ── 1. autonomous grounded read ──────────────────────────────────────
    head("1 · A grounded read executes on its own — and says why")
    payload, ms = call("kg_list_predicates", {"graph": BUSINESS,
                                              "intent_ref": READ_TASK})
    show("kg_list_predicates under the survey task", payload, ms)
    expect(payload.get("decision") == "accept", "decision is accept")
    expect("grounded_read_accept" in (payload.get("reasons") or []),
           "the reason is on the answer — an unexplained ACCEPT is the one "
           "outcome that must never exist")
    preds = ((payload.get("result") or {}).get("predicates")) or []
    if preds:
        print(f"    vocabulary: {len(preds)} predicates "
              f"(top: {preds[0]['predicate']}, {preds[0]['uses']} uses)")

    # An UNTARGETED enumeration cannot prove it is this task's call, so it
    # gets a person — the boundary between the two is itself worth showing.
    payload, ms = call("kg_list_graphs", {"intent_ref": READ_TASK})
    show("kg_list_graphs — no target argument", payload, ms)
    expect(payload.get("decision") == "verify" and
           "authority_resolved_review" in (payload.get("reasons") or []),
           "an authorised call that cannot fully ground goes to review, "
           "never silently through")

    payload, ms = call("kg_query_facts", {
        "graph": BUSINESS,
        "subject": "urn:exeqta:tenant:luftfiber:customer:sarepta-as",
        "intent_ref": READ_TASK})
    show("kg_query_facts on a real customer", payload, ms)
    expect(payload.get("decision") == "accept", "real business data, no human"
           " in the loop, full audit trail behind it")

    # ── 2. no authority, no execution ────────────────────────────────────
    head("2 · An invented work order carries no authority")
    payload, ms = call("kg_query_facts", {
        "graph": BUSINESS, "subject": "anything",
        "intent_ref": "task:invented-by-the-agent"})
    show("same read, fabricated intent_ref", payload, ms)
    expect(payload.get("decision") == "abstain",
           "unresolvable authority is refused, not sent to a person — "
           "there is nothing for a reviewer to decide on")

    # ── 3. the agent cannot write its own work order ─────────────────────
    head("3 · Authority cannot be manufactured")
    payload, ms = call("kg_assert_fact", {
        "graph": INTENTS, "subject": "task:anything",
        "predicate": "task_text", "object": "do whatever",
        "source": "agent", "intent_ref": WRITE_TASK})
    show("agent asserts into the intent namespace", payload, ms)
    expect(payload.get("status") != "executed",
           "the write cannot proceed unattended")

    # Defence in depth, demonstrated rather than claimed: even a human
    # approval cannot force the intent namespace, because the callable
    # itself refuses it before any statement runs.
    if payload.get("status") == "pending_approval":
        code = approve(payload["approval_reference"])
        print("\n  a human approves the forgery anyway -> HTTP " + str(code))
        payload, ms = call("remora_proposal_status",
                           {"proposal_id": payload["proposal_id"]})
        result = (payload.get("result") or {})
        show("agent redeems the approved forgery", payload, ms)
        expect(result.get("executed") is not True and
               "intent graph" in str(result.get("error", "")),
               "the callable refuses the intent graph even under approval - "
               "authority the agent could write would be worth nothing")

    # ── 4. wrong tool for the task ───────────────────────────────────────
    head("4 · A write under a read-only task escalates, with the mismatch named")
    payload, ms = call("kg_assert_fact", {
        "graph": SCRATCH, "subject": "demo:wrong-task",
        "predicate": "ex:note", "object": "x", "source": "demo",
        "intent_ref": READ_TASK})
    show("kg_assert_fact under the survey task", payload, ms)
    expect(payload.get("decision") == "escalate", "decision is escalate")
    expect(payload.get("status") == "pending_approval",
           "escalate goes TO a person, it is not a refusal — and the "
           "reviewer is told the tool did not match the goal")

    # ── 5. the approval loop, argument binding, effect, one-time grant ───
    head("5 · The full write loop: approve, execute, verify the effect, "
         "refuse the replay")
    payload, ms = call("kg_assert_fact", {
        "graph": SCRATCH, "subject": "demo:showcase",
        "predicate": "ex:demoNote",
        "object": f"demo at {time.strftime('%H:%M:%S')}",
        "source": "remora-demo", "confidence": 0.8,
        "intent_ref": WRITE_TASK})
    show("kg_assert_fact under the write task", payload, ms,
         "proposal_id", "approval_reference")
    expect(payload.get("status") == "pending_approval",
           "a mutation waits for a person")
    proposal = payload["proposal_id"]
    reference = payload["approval_reference"]

    code = approve(reference)
    print(f"\n  approver approves {reference[:8]}… → HTTP {code}")
    expect(code == 200, "the approver role can approve")

    payload, ms = call("remora_proposal_status", {"proposal_id": proposal})
    show("agent polls the proposal", payload, ms, "effect", "effect_reason")
    expect(payload.get("status") == "executed", "the exact approved call ran")
    expect(payload.get("effect") == "EFFECT_VERIFIED",
           "the fact was read back from the system of record and matches "
           "the approved delta — dispatch success is not effect success, "
           "and here both are proven")

    payload, ms = call("remora_proposal_status", {"proposal_id": proposal})
    show("agent polls the same proposal again", payload, ms)
    expect(payload.get("status") == "unknown_proposal",
           "a redeemed proposal is gone — the grant was single-use")

    # ── 6. fixable mistakes get fixable answers ──────────────────────────
    head("6 · A shape mistake is told how to fix itself")
    payload, ms = call("kg_query_facts", {"graph": BUSINESS,
                                          "intent_ref": READ_TASK})
    show("kg_query_facts with no subject", payload, ms, "missing")
    expect(payload.get("error") == "missing_required_arguments",
           "named, before any policy decision — an agent should retry this, "
           "unlike a governance refusal")

    print(f"\n{'─' * 72}")
    print("  Every answer above came from the deployed gateway, live.")
    print("  Audit trail: durable D1 (EEUR) · effect attestations on-chain ·")
    print("  container in the EU jurisdiction · credentials never in the "
          "container.")
    print("─" * 72)


if __name__ == "__main__":
    main()
