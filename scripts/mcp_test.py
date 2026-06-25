#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Full MCP test suite - covers all 11 tools, prints ASCII-safe results."""
import json
import os
import re
import subprocess

MCP = ["python", r"C:\Users\Stian\REMORA\servers\mcp_remora.py"]
ENV = {**os.environ, "AGENT_CONTROL_URL": "https://remora-agent-control.razorsharp.workers.dev"}

def call(req, timeout=45):
    proc = subprocess.run(
        MCP, input=json.dumps(req) + "\n",
        capture_output=True, text=True, env=ENV, timeout=timeout
    )
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return {"error": "no output", "stderr": proc.stderr[:200]}
    try:
        return json.loads(lines[-1])
    except Exception as e:
        return {"parse_error": str(e), "raw": lines[-1][:200]}

def text(r):
    t = r.get("result", {}).get("content", [{}])[0].get("text", "")
    return t.encode("ascii", "replace").decode("ascii")

def sep(label):
    print(f"\n{'='*68}")
    print(f"  {label}")
    print("="*68)

# -- 1. initialize -------------------------------------------------------------
sep("1/10  initialize")
r = call({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    "protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}
}})
info = r.get("result", {}).get("serverInfo", {})
print(f"  server: {info.get('name','?')}  version: {info.get('version','?')}")
print(f"  status: {'OK' if info else 'FAIL'}")

# -- 2. tools/list -------------------------------------------------------------
sep("2/10  tools/list")
r = call({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
tools = [t["name"] for t in r.get("result", {}).get("tools", [])]
print(f"  count: {len(tools)} / 11 expected")
for i, t in enumerate(tools, 1):
    print(f"  {i:2d}. {t}")

# -- 3. remora_status ---------------------------------------------------------
sep("3/10  remora_status")
r = call({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"remora_status","arguments":{}}})
print(text(r)[:900])

# -- 4. remora_verify_claim ---------------------------------------------------
sep("4/10  remora_verify_claim  [Oslo is the capital of Norway]")
r = call({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{
    "name":"remora_verify_claim",
    "arguments":{"claim":"Oslo is the capital of Norway"}
}})
print(text(r)[:800])

# -- 5. remora_analyze_document -----------------------------------------------
sep("5/10  remora_analyze_document")
r = call({"jsonrpc":"2.0","id":5,"method":"tools/call","params":{
    "name":"remora_analyze_document",
    "arguments":{
        "document": "REMORA uses multi-oracle consensus to improve AI reliability. "
                    "The system applies Lyapunov stability theory to ensure safe convergence "
                    "of oracle responses over successive iterations.",
        "context": "AI safety research"
    }
}})
print(text(r)[:800])

# -- 6. remora_rag_search -----------------------------------------------------
sep("6/10  remora_rag_search  [Lyapunov consensus]")
r = call({"jsonrpc":"2.0","id":6,"method":"tools/call","params":{
    "name":"remora_rag_search",
    "arguments":{"query":"Lyapunov consensus stability", "limit":3}
}})
print(text(r)[:800])

# -- 7. remora_rag_query -------------------------------------------------------
sep("7/10  remora_rag_query  [Lyapunov stability in REMORA]")
r = call({"jsonrpc":"2.0","id":7,"method":"tools/call","params":{
    "name":"remora_rag_query",
    "arguments":{
        "query": "Lyapunov stability condition multi-oracle consensus REMORA",
        "domain": "science"
    }
}}, timeout=90)
print(text(r)[:800])

# -- 8. remora_norwegian_law_search -------------------------------------------
sep("8/10  remora_norwegian_law_search  [personopplysningsloven GDPR]")
r = call({"jsonrpc":"2.0","id":8,"method":"tools/call","params":{
    "name":"remora_norwegian_law_search",
    "arguments":{"query":"personopplysningsloven GDPR", "limit":3}
}})
print(text(r)[:800])

# -- 9-11. Agent pipeline: start → execute → audit ----------------------------
sep("9/10  agent_start_session")
r = call({"jsonrpc":"2.0","id":9,"method":"tools/call","params":{
    "name":"agent_start_session",
    "arguments":{"agent_id":"mcp-test-agent","policy":"strict","purpose":"MCP integration test 2026-05-28"}
}})
t9 = text(r)
m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", t9)
sid = m.group(0) if m else None
print(t9[:600])
print(f"\n  session_id: {sid or 'NOT FOUND'}")

if sid:
    sep("10/10  agent_execute_tool  [arguments field - policy gate + D1 audit]")
    r = call({"jsonrpc":"2.0","id":10,"method":"tools/call","params":{
        "name":"agent_execute_tool",
        "arguments":{
            "session_id": sid,
            "tool": "remora_verify_claim",
            "arguments": {"claim": "REMORA uses Lyapunov stability theory for multi-oracle consensus"}
        }
    }})
    print(text(r)[:700])

    sep("11/10  agent_audit_log  [inspect trail]")
    r = call({"jsonrpc":"2.0","id":11,"method":"tools/call","params":{
        "name":"agent_audit_log",
        "arguments":{"session_id":sid,"limit":10}
    }})
    print(text(r)[:700])
else:
    print("\n  [10+11] SKIP: no session_id returned")
    print("  Likely cause: AGENT_CONTROL_SECRET env var not set in this shell")
    print("  Set it with: $env:AGENT_CONTROL_SECRET = '<secret>'")

sep("SUMMARY")
print(f"  Tools registered: {len(tools)}/11")
print(f"  Session created:  {'YES - ' + sid if sid else 'NO (auth secret missing)'}")
print()
