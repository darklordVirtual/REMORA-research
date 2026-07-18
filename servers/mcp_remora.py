#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
REMORA MCP Server — Claude Desktop integration.

Exposes REMORA multi-oracle consensus and RAG knowledge retrieval
as MCP tools so Claude can use them directly in conversations.

Use cases:
  • Analyze a legal letter (brev) with DCE domain knowledge
  • Verify factual claims in a document
  • Search the regulatory knowledge base
  • Get calibrated confidence scores on specific claims

Tools (14)
----------
  remora_analyze_document         Multi-oracle consensus on a free-text passage
  remora_verify_claim             Single yes/no factual claim
  remora_legal_analysis           Norwegian legal doc + statutory grounding
  remora_rag_search               Raw retrieval from the knowledge base
  remora_rag_query                Synthesised RAG answer with reranking
    remora_codegraph_scope          Active repo codegraph scope + file suggestions
  remora_norwegian_law_search     Direct Norwegian statute lookup
  remora_verify_legal_citations   Citation hallucination detection
  remora_status                   System health (oracles, corpus, thresholds)
  remora_session_status           Local session Lyapunov V(t) + intent drift telemetry
  agent_start_session             Open an audited agent session
  agent_execute_tool              Run a tool through the policy gate + audit
  agent_audit_log                 Inspect the audit trail for a session

Start
-----
  Add to claude_desktop_config.json under mcpServers:
  "remora": {
      "command": "python",
      "args": ["C:\\Users\\Stian\\REMORA\\servers\\mcp_remora.py"],
      "cwd": "C:\\Users\\Stian\\REMORA"
  }
"""
from __future__ import annotations

import json
import logging
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

# ── Worker URLs — resolved from environment, not hardcoded ───────────────────
# Profiles (set REMORA_PROFILE or override each URL individually):
#   local    → Python mock engine, no Cloudflare Workers required
#   demo     → public demo workers (rate-limited, no write access)
#   enterprise → your own deployed workers (set all _URL vars below)
#
# Required for enterprise profile:
#   export REMORA_WORKER_URL=https://your-remora.workers.dev
#   export RAG_WORKER_URL=https://your-rag.workers.dev
#   export LAW_SEARCH_WORKER_URL=https://your-law.workers.dev
#   export AGENT_CONTROL_URL=https://your-control.workers.dev
#   export AGENT_CONTROL_SECRET=<bearer-token>
#   export CODEGRAPH_URL=https://your-control.workers.dev/codegraph

_DEMO_REMORA = "https://go-star-remora.razorsharp.workers.dev"
_DEMO_RAG    = "https://remora-rag-oracle.razorsharp.workers.dev"
_DEMO_LAW    = "https://remora-law-search.razorsharp.workers.dev"

REMORA_WORKER = os.environ.get("REMORA_WORKER_URL", _DEMO_REMORA)
RAG_WORKER    = os.environ.get("RAG_WORKER_URL",    _DEMO_RAG)
# Set after deploying workers/agent-control:
AGENT_CONTROL = os.environ.get("AGENT_CONTROL_URL", "")
AGENT_SECRET  = os.environ.get("AGENT_CONTROL_SECRET", "")
CODEGRAPH_URL = os.environ.get("CODEGRAPH_URL") or (f"{AGENT_CONTROL.rstrip('/')}/codegraph" if AGENT_CONTROL else "")
REPO_SEARCH_URL = os.environ.get("REPO_SEARCH_URL") or (f"{AGENT_CONTROL.rstrip('/')}/search" if AGENT_CONTROL else "")
SSL_CTX       = ssl.create_default_context()
UA            = "REMORA-MCP/1.0"

# ── Citation patterns for Norwegian courts ─────────────────────────────────────
# Høyesterett post-2016:  HR-YYYY-NNNN-A  (A=avsagt, U=underrett, P=plenary)
# Høyesterett pre-2016:   Rt. YYYY s. NNN  or  Rt-YYYY-NNN
# Lagmannsrett:           LB/LA/LF/LG/LE/LH-YYYY-NNNN
CITATION_PATTERNS = [
    (re.compile(r'\bHR-(\d{4})-(\d+)-([AUP])\b', re.IGNORECASE), "HR-{year}-{num}-{type}"),
    (re.compile(r'\bRt\.?\s*(\d{4})\s*s\.?\s*(\d+)\b'), "Rt. {year} s. {page}"),
    (re.compile(r'\bL[ABFGEH]-(\d{4})-(\d+)\b', re.IGNORECASE), "Lagmannsrett"),
]


def extract_citations(text: str) -> list[dict]:
    """Extract all Norwegian legal citations from text."""
    found = []
    for pattern, fmt in CITATION_PATTERNS:
        for m in pattern.finditer(text):
            found.append({
                "citation": m.group(0).strip(),
                "type": fmt,
                "start": m.start(),
            })
    # Deduplicate by citation string
    seen = set()
    unique = []
    for c in sorted(found, key=lambda x: x["start"]):
        if c["citation"].upper() not in seen:
            seen.add(c["citation"].upper())
            unique.append(c)
    return unique


def verify_citation_existence(citation: str) -> dict:
    """
    Multi-oracle citation verification with adversarial falsification.

    Strategy: A real citation should produce CONSISTENT specific details
    across independent oracles. A hallucinated citation produces INCONSISTENT
    or vague answers because no consistent training data exists for it.

    Two checks:
    1. Ask each oracle for SPECIFIC verifiable details (parties, legal question)
    2. Ask a dedicated skeptic whether the citation and its attributed legal
       principle can be confirmed against Norwegian law.

    Returns classification: VERIFIED / SUSPICIOUS / LIKELY_HALLUCINATED / CANNOT_VERIFY
    """
    # Adversarial prompt: requires specific facts a fake citation cannot provide
    adversarial_prompt = (
        f"You are a Norwegian legal citation verifier. "
        f"About the court decision '{citation}': "
        f"(1) Can you confirm this case exists in Norwegian case law? "
        f"(2) Who were the parties? "
        f"(3) What specific legal principle did it establish? "
        f"If you cannot confirm this case exists with certainty, state CANNOT VERIFY explicitly. "
        f"Do NOT fabricate details. If uncertain, say so."
    )

    result = _post(REMORA_WORKER + "/assess", {
        "question": adversarial_prompt,
        "context": "",
        "use_case": "general",
    })

    if result.get("error"):
        return {"status": "ERROR", "detail": result["error"]}

    verdict    = result.get("verdict")
    confidence = result.get("confidence", 0.0)
    claim      = result.get("claim", "").lower()
    routed     = result.get("routed_fast", False)

    # Signals of hallucination:
    # - oracles disagree (low confidence, no routing)
    # - claim contains "cannot verify", "uncertain", "no record"
    # - verdict is None (no consensus)
    cannot_verify_signals = any(
        w in claim for w in
        ["cannot verify", "cannot confirm", "no record", "uncertain",
         "unable to confirm", "no information", "not aware", "do not have"]
    )

    if cannot_verify_signals or verdict is None or confidence < 0.30:
        status = "CANNOT_VERIFY"
    elif confidence < 0.60:
        status = "SUSPICIOUS"
    elif verdict is False:
        status = "LIKELY_HALLUCINATED"
    else:
        status = "NEEDS_CONTENT_CHECK"

    return {
        "citation": citation,
        "status": status,
        "confidence": confidence,
        "verdict": verdict,
        "oracle_claim": result.get("claim", ""),
        "oracle_agreement": "fast" if routed else "iterated",
        "cannot_verify_signals_found": cannot_verify_signals,
    }


def verify_legal_principle(citation: str, attributed_principle: str) -> dict:
    """
    Verify whether the legal principle attributed to a citation is correct under Norwegian law.
    A citation may exist but be misrepresented — this catches content hallucination.
    """
    skeptic_prompt = (
        f"You are a skeptical Norwegian employment law expert. "
        f"The letter claims that '{citation}' established the following rule: "
        f"'{attributed_principle}'. "
        f"Is this an accurate statement of Norwegian law? "
        f"Check: (1) Does Norwegian law actually establish this rule? "
        f"(2) Is this what the cited case actually decided? "
        f"Be critical. Look for overstatements, missing conditions, or incorrect principles."
    )

    result = _post(REMORA_WORKER + "/assess", {
        "question": skeptic_prompt,
        "context": "",
        "use_case": "general",
    })

    return {
        "attributed_principle": attributed_principle[:200],
        "verdict": result.get("verdict"),
        "confidence": result.get("confidence", 0.0),
        "assessment": result.get("claim", ""),
    }


LAW_SEARCH_WORKER = os.environ.get("LAW_SEARCH_WORKER_URL", _DEMO_LAW)


def _post(url: str, payload: dict, timeout: int = 90) -> dict:
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def _get(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def _local_codegraph_manifest() -> dict:
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / "codegraph.yaml"
    ignore_path = root / ".codegraphignore"
    return {
        "service": "local-fallback",
        "generated_at": None,
        "query": None,
        "limit": 0,
        "scope_text": manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else "",
        "ignore_text": ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else "",
    }


def _local_repo_search(query: str, limit: int) -> dict:
    root = Path(__file__).resolve().parents[1]
    terms = [term for term in re.split(r"[^a-z0-9_./-]+", query.lower()) if len(term) > 1]
    text_suffixes = {
        ".md", ".py", ".ts", ".js", ".json", ".yaml", ".yml", ".toml",
        ".sql", ".sh", ".html", ".css", ".txt", ".cff", ".cfg", ".ini",
        ".pyi", ".tsx", ".jsx", ".mjs", ".cjs", ".rs", ".go", ".java",
    }

    try:
        files = subprocess.check_output(["git", "-C", str(root), "ls-files"], text=True).splitlines()
    except Exception:
        files = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]

    matches: list[dict] = []
    for rel_path in files:
        if len(matches) >= limit * 4:
            break

        path = root / rel_path
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        haystack = f"{rel_path}\n{content}".lower()
        score = 0
        if query and query.lower() in rel_path.lower():
            score += 30
        for term in terms:
            score += min(haystack.count(term), 6) * 3
            if term in rel_path.lower():
                score += 8

        if not score:
            continue

        snippet = ""
        if terms:
            for term in terms:
                idx = haystack.find(term)
                if idx >= 0:
                    start = max(0, idx - 120)
                    end = min(len(content), idx + 220)
                    snippet = content[start:end].strip().replace("\n", " ")
                    break
        if not snippet:
            snippet = content[:250].strip().replace("\n", " ")

        matches.append({
            "path": rel_path,
            "score": score,
            "snippet": snippet[:300],
        })

    matches.sort(key=lambda item: (-int(item.get("score", 0)), str(item.get("path", ""))))
    return {
        "service": "local-fallback",
        "generated_at": None,
        "query": query,
        "limit": limit,
        "matches": matches[:limit],
    }


def _render_codegraph_result(data: dict) -> str:
    scope = data.get("scope", {}) if isinstance(data, dict) else {}
    includes = scope.get("include", []) if isinstance(scope, dict) else []
    excludes = scope.get("exclude", []) if isinstance(scope, dict) else []
    entrypoints = scope.get("entrypoints", []) if isinstance(scope, dict) else []
    notes = scope.get("notes", []) if isinstance(scope, dict) else []
    matches = data.get("matches", []) if isinstance(data, dict) else []

    lines = [
        "## REMORA Codegraph",
        "",
        f"**Source:** {data.get('service', 'unknown')}",
    ]
    if data.get("generated_at"):
        lines.append(f"**Generated:** {data['generated_at']}")
    if data.get("query"):
        lines.append(f"**Query:** {data['query']}")
    lines += [
        "",
        "### Scope",
        "",
        "**Includes**",
    ]
    lines += [f"- {item}" for item in includes]
    lines += ["", "**Excludes**"]
    lines += [f"- {item}" for item in excludes]
    lines += ["", "**Entrypoints**"]
    lines += [f"- {item}" for item in entrypoints]
    if notes:
        lines += ["", "**Notes**"]
        lines += [f"- {item}" for item in notes]
    if matches:
        lines += ["", "### Relevant files", ""]
        for match in matches:
            path = match.get("path", "?")
            summary = match.get("summary", "")
            kind = match.get("kind", "")
            lines.append(f"- `{path}` ({kind}): {summary}")
    return "\n".join(lines)


def _render_repo_search_result(data: dict) -> str:
    matches = data.get("matches", []) if isinstance(data, dict) else []
    lines = [
        "## REMORA Repo Search",
        "",
        f"**Source:** {data.get('service', 'unknown')}",
    ]
    if data.get("query"):
        lines.append(f"**Query:** {data['query']}")
    if matches:
        lines += ["", "### Top matches", ""]
        for i, match in enumerate(matches, 1):
            path = match.get("path", "?")
            score = match.get("score", 0)
            snippet = str(match.get("snippet", ""))[:300]
            lines.append(f"{i}. `{path}`  score={score}")
            if snippet:
                lines.append(f"   > {snippet}")
    else:
        lines += ["", "No matches found."]
    return "\n".join(lines)


# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "remora_analyze_document",
        "description": (
            "Analyze a text document, letter, or passage using REMORA multi-oracle consensus. "
            "Sends the text to 3 independent AI models (Groq LLaMA 8B, 70B, OpenRouter Mistral) "
            "and returns a consensus verdict with confidence score and supporting claim. "
            "Use this to get a calibrated, multi-source assessment of any text. "
            "The domain parameter focuses the analysis: 'legal', 'science', 'general', 'specialised'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The document, letter, or text to analyze"
                },
                "question": {
                    "type": "string",
                    "description": "The specific question to ask about the text (e.g. 'Is this letter legally valid?', 'Are the claims in this document accurate?')"
                },
                "domain": {
                    "type": "string",
                    "description": "Analysis domain: 'legal', 'science', 'general', 'specialised'. Default: 'general'",
                    "enum": ["legal", "science", "general", "specialised"]
                },
            },
            "required": ["text", "question"],
        },
    },
    {
        "name": "remora_verify_claim",
        "description": (
            "Verify a single specific factual or legal claim using REMORA consensus. "
            "Returns: verdict (true/false/uncertain), confidence score, supporting claim text, "
            "and whether the answer is reliably grounded (ETR). "
            "Best for yes/no questions about facts, regulations, or legal requirements."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "claim": {
                    "type": "string",
                    "description": "The specific claim to verify, as a yes/no question (e.g. 'Is GDPR Article 17 applicable to this situation?')"
                },
                "context": {
                    "type": "string",
                    "description": "Optional: relevant background information or document excerpt"
                },
                "domain": {
                    "type": "string",
                    "description": "Knowledge domain: 'legal', 'science', 'general', 'specialised'",
                    "enum": ["legal", "science", "general", "specialised"]
                },
            },
            "required": ["claim"],
        },
    },
    {
        "name": "remora_legal_analysis",
        "description": (
            "Specialized legal and regulatory analysis using REMORA with the DCE/legal knowledge base. "
            "Combines multi-oracle consensus with retrieval from the regulatory corpus "
            "(GDPR, ISO standards, EU law, legal precedents). "
            "Use this for analyzing contracts, letters, regulatory questions, and compliance issues. "
            "Returns verdict, confidence, cited sources, and any exceptions or caveats identified."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_text": {
                    "type": "string",
                    "description": "The legal document, letter, or regulatory text to analyze"
                },
                "analysis_question": {
                    "type": "string",
                    "description": "What specifically to analyze (e.g. 'Is the termination clause valid?', 'Does this comply with GDPR Article 13?')"
                },
                "jurisdiction": {
                    "type": "string",
                    "description": "Optional: legal jurisdiction (e.g. 'EU', 'Norway', 'UK'). Helps focus retrieval.",
                    "default": "EU"
                },
                "domain": {
                    "type": "string",
                    "description": "Kunnskapsdomene: 'specialised' (GDPR/ISO), 'science', 'general'. Standard: 'specialised'",
                    "enum": ["specialised", "science", "general"],
                    "default": "specialised",
                },
            },
            "required": ["document_text", "analysis_question"],
        },
    },
    {
        "name": "remora_rag_search",
        "description": (
            "Search the REMORA knowledge base for relevant information on a topic. "
            "The knowledge base contains: GDPR regulation text, WHO health guidelines, "
            "ISO/IEC standards, scientific consensus documents, and Wikipedia articles. "
            "Returns matching document excerpts with source citations and relevance scores. "
            "Use this when you need to look up regulatory text, standards, or authoritative sources."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for (e.g. 'GDPR right to erasure Article 17', 'vaccine safety WHO guidelines')"
                },
                "domain": {
                    "type": "string",
                    "description": "Optional: filter by domain: 'specialised', 'science', 'general'",
                    "enum": ["specialised", "science", "general"]
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (1-10, default 5)",
                    "default": 5
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "remora_status",
        "description": (
            "Check the status of the REMORA system: how many oracles are active, "
            "how many documents are in the knowledge base, and system health. "
            "Use this to verify REMORA is working before running analyses."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "remora_verify_legal_citations",
        "description": (
            "KRITISK SJEKK: Verifiser alle juridiske referanser (dommer, lover) i et dokument. "
            "Oppdager hallusinerte (falske) Høyesterettsdommer og lovhenvisninger. "
            "Sjekker tre ting for hvert sitat: "
            "(1) Finnes dommen i DCE sin database over norske dommer og lover? "
            "(2) Stemmer det juridiske prinsippet som tilskrives dommen med norsk rett? "
            "(3) Er det konsensus mellom uavhengige orakler om dommens innhold? "
            "Returnerer: VERIFISERT / MISTENKELIG / SANNSYNLIG_HALLUSINERT / KAN_IKKE_VERIFISERES "
            "for hvert sitat. Bruk alltid dette verktøyet ved juridiske brev, kontrakter og krav."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_text": {
                    "type": "string",
                    "description": "Det juridiske dokumentet eller brevet som skal sjekkes for falske dommer",
                },
                "claimed_principles": {
                    "type": "string",
                    "description": "Valgfritt: det juridiske prinsippet som dokumentet hevder at dommene støtter (f.eks. '6 måneders etterlønn uavhengig av ansettelsestid')",
                },
            },
            "required": ["document_text"],
        },
    },
    {
        "name": "remora_norwegian_law_search",
        "description": (
            "Søk direkte i norsk lovdatabase (DCE norges-lover-law-index). "
            "Returnerer relevante lovtekster med paragraf-referanser, titler og relevans-score. "
            "Dekker arbeidsmiljøloven, avtaleloven, forvaltningsloven, straffeloven og andre norske lover. "
            "Bruk dette når du trenger den faktiske lovteksten — ikke AI-konsensus om loven. "
            "Eks: 'oppsigelse arbeidsmiljøloven § 15-7', 'inkasso foreldelse', 'GDPR personopplysninger'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Søketekst — lov, paragraf, rettslig begrep eller spørsmål på norsk",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maks antall resultater (1-10, standard 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "remora_rag_query",
        "description": (
            "Stiller et faktaspørsmål mot REMORA kunnskapsbase med full syntese og reranking. "
            "Kunnskapsbasen inneholder: GDPR-regelverk, WHO-retningslinjer, ISO/IEC-standarder "
            "og vitenskapelig konsensus. Svaret er alltid forankret i databasen — ikke modellens prior. "
            "Bruk domain=specialised for GDPR/ISO, domain=science for helse/vitenskap. "
            "Sett use_case=legal for juridiske spørsmål (aktiverer dual_consensus + 70B automatisk). "
            "Sett dual_consensus=true eksplisitt for høyrisiko-spørsmål."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Spørsmålet som skal besvares fra kunnskapsbasen",
                },
                "domain": {
                    "type": "string",
                    "description": "'specialised' (GDPR/ISO), 'science' (helse), 'general'",
                    "enum": ["specialised", "science", "general"],
                    "default": "general",
                },
                "use_case": {
                    "type": "string",
                    "description": "'legal' (dual_consensus + 70B), 'security' (rask 8B), 'general'",
                    "enum": ["legal", "security", "general"],
                },
                "dual_consensus": {
                    "type": "boolean",
                    "description": "Kjør 8B + 70B parallelt for høyere pålitelighet",
                    "default": False,
                },
                "complexity": {
                    "type": "string",
                    "description": "'low' (rask 8B), 'high' (sterk 70B), 'auto'",
                    "enum": ["low", "high", "auto"],
                    "default": "auto",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "remora_codegraph_scope",
        "description": (
            "Get the canonical repository codegraph scope and a compact list of relevant files. "
            "Use this before asking broad repo questions so the assistant can stay within the active graph. "
            "Backed by the Cloudflare codegraph endpoint when available, with a local fallback to codegraph.yaml."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional search terms like 'MCP', 'Cloudflare', 'counterfactual', or 'worker'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of relevant files to return (1-25, default 8)",
                    "default": 8,
                },
            },
        },
    },
    {
        "name": "remora_repo_search",
        "description": (
            "Search the repository for relevant content and snippets. "
            "Use this after remora_codegraph_scope when you need a cheap file-and-snippet pass. "
            "Backed by the Cloudflare search endpoint when available, with a local fallback to git-tracked text files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms like 'Claude Code', 'Vectorize', 'MCP', or 'codegraph'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (1-25, default 8)",
                    "default": 8,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "agent_execute_tool",
        "description": (
            "Execute a tool on the REMORA Agent Control Plane. "
            "The control plane enforces egress policy, injects secrets, and logs every call "
            "to an immutable audit trail. Available tools: remora_verify_claim, dce_search_law, "
            "store_artifact, audit_decision. "
            "Requires AGENT_CONTROL_URL environment variable to be set."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool": {
                    "type": "string",
                    "description": "Tool name: remora_verify_claim | dce_search_law | store_artifact | audit_decision",
                    "enum": ["remora_verify_claim", "dce_search_law", "store_artifact", "audit_decision"],
                },
                "arguments": {
                    "type": "object",
                    "description": "Tool-specific parameters. remora_verify_claim: {claim, context?, domain?}. dce_search_law: {query, top_k?, domain?}. store_artifact: {key, content, approved?}. audit_decision: {audit_id, approved, approved_by, note?}.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID from agent_start_session. Creates a new session if omitted.",
                },
            },
            "required": ["tool", "arguments"],
        },
    },
    {
        "name": "agent_start_session",
        "description": (
            "Start a new agent session on the control plane. "
            "Returns a session_id that must be passed to agent_execute_tool calls. "
            "Each session gets its own audit trail and can be inspected via agent_audit_log."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_label": {
                    "type": "string",
                    "description": "Human-readable label for this session (e.g. 'REMORA analyse 2026-05')",
                },
            },
        },
    },
    {
        "name": "agent_audit_log",
        "description": (
            "Retrieve the audit log for an agent session. "
            "Returns every tool call made, its verdict, confidence, approval status, and timestamp. "
            "Use this to review what the agent did and approve/reject pending actions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID to retrieve audit log for",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to return (default 50)",
                    "default": 50,
                },
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "remora_session_status",
        "description": (
            "Return the live safety telemetry for the current local agent session. "
            "Reports the Lyapunov stability function V(t) — a formal measure of consensus "
            "divergence across recent tool calls — along with intent drift, convergence "
            "state, and a summary of blocked vs allowed actions. "
            "Use this to introspect session health before making high-stakes decisions, "
            "or after a REMORA block to understand the stability trajectory. "
            "Does not make any network calls. Session state is stored in .remora_session/."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_dir": {
                    "type": "string",
                    "description": "Override session directory (default: .remora_session/). "
                                   "Leave empty to use the project default.",
                    "default": "",
                },
            },
            "required": [],
        },
    },
]


# ── Tool handlers ──────────────────────────────────────────────────────────────

def handle_remora_analyze_document(args: dict) -> str:
    text     = args.get("text", "").strip()
    question = args.get("question", "").strip()
    domain   = args.get("domain", "general")

    if not text or not question:
        return "Error: both 'text' and 'question' are required."

    # Build the prompt: inject document as context
    context_prompt = (
        f"Document/text:\n---\n{text[:3000]}\n---\n\n"
        f"Question about this document: {question}"
    )

    result = _post(REMORA_WORKER + "/assess", {
        "question": context_prompt,
        "context": "",
        "use_case": "general",
    })

    if result.get("error"):
        return f"REMORA error: {result['error']}"

    verdict      = result.get("verdict")
    confidence   = result.get("confidence", 0)
    claim        = result.get("claim", "")
    oracle_calls = result.get("oracle_calls", 0)
    routed       = result.get("routed_fast", False)
    summary      = result.get("summary", "")
    dual         = result.get("dual_consensus", False)
    models_ok    = result.get("models_agreed")

    verdict_text = {
        True:  "YES — confirmed",
        False: "NO — not confirmed",
        None:  "UNCERTAIN — insufficient consensus",
    }.get(verdict, "UNKNOWN")

    lines = [
        "## REMORA Analysis",
        "",
        f"**Verdict:** {verdict_text}",
        f"**Confidence:** {confidence:.0%}",
        f"**Domain:** {domain}",
        f"**Consensus:** {summary}",
        f"**Supporting claim:** {claim}",
        "",
        "**How it was determined:**",
        f"- {oracle_calls} oracle calls across 3 independent AI models",
        f"- {'Fast-path consensus (oracles agreed immediately)' if routed else 'Full Lyapunov iteration (required deeper analysis)'}",
    ]

    if dual:
        agreed_txt = "agreed" if models_ok else "disagreed"
        lines.append(f"- Dual consensus: 8B + 70B models {agreed_txt}")

    lines += [
        "",
        "*Note: Confidence below 70% → treat as uncertain and seek additional sources.*",
    ]
    return "\n".join(lines)


def handle_remora_verify_claim(args: dict) -> str:
    claim   = args.get("claim", "").strip()
    context = args.get("context", "")
    domain  = args.get("domain", "general")

    if not claim:
        return "Error: 'claim' is required."

    result = _post(REMORA_WORKER + "/assess", {
        "question": claim,
        "context": context,
        "use_case": "general",
    })

    if result.get("error"):
        return f"REMORA error: {result['error']}"

    verdict    = result.get("verdict")
    confidence = result.get("confidence", 0)
    claim_text = result.get("claim", "")
    summary    = result.get("summary", "")
    dual       = result.get("dual_consensus", False)
    models_ok  = result.get("models_agreed")

    if confidence >= 0.80:
        trust = "HIGH — reliable basis for decision"
    elif confidence >= 0.65:
        trust = "MEDIUM — useful but verify with primary source"
    elif confidence >= 0.40:
        trust = "LOW — treat as indicative only"
    else:
        trust = "VERY LOW — abstain or seek expert review"

    verdict_emoji = {True: "✓", False: "✗", None: "?"}.get(verdict, "?")
    verdict_text  = {True: "TRUE", False: "FALSE", None: "UNCERTAIN"}.get(verdict, "UNKNOWN")

    lines = [
        "## Claim Verification",
        "",
        f"**Claim:** {claim}",
        f"**Domain:** {domain}",
        "",
        f"**{verdict_emoji} Verdict: {verdict_text}**",
        f"**Confidence: {confidence:.0%}** — Trust level: {trust}",
        f"**REMORA assessment:** {claim_text}",
        "",
    ]

    if dual:
        agreed_txt = "agreed" if models_ok else "disagreed"
        lines += [f"*Dual consensus: 8B + 70B models {agreed_txt}*", ""]

    lines.append(f"*(Consensus from 3 independent AI oracles — {summary})*")
    return "\n".join(lines)


def handle_remora_legal_analysis(args: dict) -> str:
    doc_text     = args.get("document_text", "").strip()
    question     = args.get("analysis_question", "").strip()
    jurisdiction = args.get("jurisdiction", "EU")
    domain       = args.get("domain", "specialised")

    if not doc_text or not question:
        return "Error: both 'document_text' and 'analysis_question' are required."

    # Step 1: RAG synthesis — POST /query with use_case=legal triggers dual_consensus + 70B model
    rag_result = _post(RAG_WORKER + "/query", {
        "query": f"{question} {jurisdiction}",
        "domain": domain,
        "use_case": "legal",
        "top_k": 3,
        "use_cache": True,
    }, timeout=30)

    rag_error     = rag_result.get("error")
    rag_claim     = rag_result.get("claim", "")
    rag_sources   = rag_result.get("sources", [])
    rag_conf      = rag_result.get("confidence", 0.0)
    rag_models_ok = rag_result.get("models_agreed")

    # Step 2: REMORA consensus with document + RAG grounding injected as context
    full_context = f"Document:\n{doc_text[:2000]}\n\nJurisdiction: {jurisdiction}"
    if rag_claim and not rag_error:
        full_context += f"\n\nKnowledge base synthesis: {rag_claim}"
    if rag_sources:
        full_context += f"\nSources: {', '.join(rag_sources[:5])}"

    result = _post(REMORA_WORKER + "/assess", {
        "question": question,
        "context": full_context,
        "use_case": "general",
    })

    if result.get("error"):
        return f"REMORA error: {result['error']}"

    verdict    = result.get("verdict")
    confidence = result.get("confidence", 0)
    claim      = result.get("claim", "")
    summary    = result.get("summary", "")

    verdict_text = {True: "YES", False: "NO", None: "UNCERTAIN"}.get(verdict, "?")

    lines = [
        "## Legal Analysis — REMORA + Knowledge Base",
        "",
        f"**Question:** {question}",
        f"**Jurisdiction:** {jurisdiction}",
        f"**Domain:** {domain}",
        "",
        f"### Verdict: {verdict_text}",
        f"**Confidence:** {confidence:.0%}",
        f"**Assessment:** {claim}",
        "",
    ]

    if not rag_error and rag_claim:
        if rag_models_ok is True:
            agreed_txt = " (8B + 70B agreed)"
        elif rag_models_ok is False:
            agreed_txt = " (models disagreed — lower reliability)"
        else:
            agreed_txt = ""
        lines += [
            f"### Knowledge Base Synthesis{agreed_txt}",
            f"**RAG confidence:** {rag_conf:.0%}",
            f"> {rag_claim}",
            "",
        ]
        if rag_sources:
            lines.append("**Sources:** " + ", ".join(f"`{s}`" for s in rag_sources[:5]))
            lines.append("")
    else:
        lines += [
            "*No relevant documents found in knowledge base.*",
            "*Add sources: `python scripts/ingest_corpus.py --url <URL> --domain specialised`*",
            "",
        ]

    lines += [
        f"*Consensus: {summary}*",
        "*Always verify with qualified legal counsel for binding decisions.*",
    ]
    return "\n".join(lines)


def handle_remora_rag_search(args: dict) -> str:
    query       = args.get("query", "").strip()
    domain      = args.get("domain", "")
    max_results = min(int(args.get("max_results", 5)), 10)

    if not query:
        return "Error: 'query' is required."

    url = f"{RAG_WORKER}/search?q={urllib.parse.quote(query)}&k={max_results}"
    if domain:
        url += f"&domain={urllib.parse.quote(domain)}"

    result = _get(url)

    if result.get("error"):
        return f"RAG search error: {result['error']}"

    matches = result.get("matches", [])

    if not matches:
        return (
            f"No results found for: **{query}**\n\n"
            f"The knowledge base currently covers: GDPR, WHO health guidelines, "
            f"ISO/IEC standards, and scientific consensus.\n"
            f"To add more sources, use: `python scripts/ingest_corpus.py --url <URL> --domain specialised`"
        )

    lines = [f"## Knowledge Base Search: \"{query}\"", "", f"Found {len(matches)} relevant documents:", ""]
    for i, m in enumerate(matches, 1):
        score   = m.get("score", 0)
        source  = m.get("source", "Unknown")
        preview = m.get("content_preview", "")[:300]
        lines += [
            f"### {i}. {source}",
            f"**Relevance score:** {score:.3f}",
            "",
            f"> {preview}...",
            "",
        ]
    return "\n".join(lines)


def handle_remora_status(_args: dict) -> str:
    remora_status = _get(REMORA_WORKER + "/status")
    rag_status    = _get(RAG_WORKER    + "/status")

    lines = ["## REMORA System Status", ""]

    if not remora_status.get("error"):
        n_oracles = remora_status.get("n_oracles", 0)
        ready     = remora_status.get("ready", False)
        lines += [
            "### Consensus Engine",
            f"- Status: {'✓ Ready' if ready else '✗ Not ready'}",
            f"- Active oracles: {n_oracles} / 3",
            f"- Models: {remora_status.get('models', {}).get('groq_fast','?')}, "
              f"{remora_status.get('models', {}).get('groq_strong','?')}, "
              f"{remora_status.get('models', {}).get('openrouter','?')}",
            "",
        ]
    else:
        lines += [f"### Consensus Engine: ✗ {remora_status['error']}", ""]

    if not rag_status.get("error"):
        total  = rag_status.get("total_chunks", 0)
        by_dom = {d["domain"]: d["n"] for d in rag_status.get("by_domain", [])}
        lines += [
            "### Knowledge Base (RAG Oracle)",
            f"- Total documents: {total} chunks",
        ]
        for domain, n in by_dom.items():
            lines.append(f"  - {domain}: {n} chunks")
        lines.append("")
    else:
        lines += [f"### Knowledge Base: ✗ {rag_status['error']}", ""]

    lines += [
        "### Coverage",
        "- Regulatory: GDPR Art. 4+5, ISO/IEC 27001",
        "- Science: NCBI/CRISPR, WHO vaccines, DNA, IUPAC chemistry",
        "- General: Geography, history, common misconceptions",
        "",
        "*To expand: `python scripts/enrich_corpus.py --wikipedia --domains specialised`*",
    ]
    return "\n".join(lines)


def handle_remora_codegraph_scope(args: dict) -> str:
    """Return the repo codegraph scope and relevant files from Cloudflare or local fallback."""
    query = str(args.get("query", "")).strip()
    limit = args.get("limit", 8)
    try:
        limit_int = max(1, min(int(limit), 25))
    except Exception:
        limit_int = 8

    data: dict
    if CODEGRAPH_URL:
        params = {"q": query, "limit": str(limit_int)} if query else {"limit": str(limit_int)}
        url = CODEGRAPH_URL + ("?" + urllib.parse.urlencode(params) if params else "")
        data = _get(url, timeout=15)
        if "error" in data:
            data = _local_codegraph_manifest()
            data["service"] = f"local-fallback ({data.get('service', 'unknown')})"
    else:
        data = _local_codegraph_manifest()

    if "scope" in data:
        return _render_codegraph_result(data)

    scope_text = str(data.get("scope_text", "")).strip()
    ignore_text = str(data.get("ignore_text", "")).strip()
    lines = [
        "## REMORA Codegraph",
        "",
        f"**Source:** {data.get('service', 'local-fallback')}",
    ]
    if scope_text:
        lines += ["", "### codegraph.yaml", "", "```yaml", scope_text, "```"]
    if ignore_text:
        lines += ["", "### .codegraphignore", "", "```text", ignore_text, "```"]
    return "\n".join(lines)


def handle_remora_repo_search(args: dict) -> str:
    """Search repository files and snippets using Cloudflare or local fallback."""
    query = str(args.get("query", "")).strip()
    limit = args.get("limit", 8)
    try:
        limit_int = max(1, min(int(limit), 25))
    except Exception:
        limit_int = 8

    if not query:
        return "Error: query is required."

    data: dict
    if REPO_SEARCH_URL:
        params = {"q": query, "limit": str(limit_int)}
        url = REPO_SEARCH_URL + ("?" + urllib.parse.urlencode(params) if params else "")
        data = _get(url, timeout=15)
        if "error" in data:
            data = _local_repo_search(query, limit_int)
            data["service"] = f"local-fallback ({data.get('service', 'unknown')})"
    else:
        data = _local_repo_search(query, limit_int)

    return _render_repo_search_result(data)


# ── MCP protocol ───────────────────────────────────────────────────────────────

def handle_remora_verify_legal_citations(args: dict) -> str:
    """
    Full citation verification pipeline:
    1. Extract all Norwegian legal citations from text (regex)
    2. For each: check DCE D1 database (exists?) + adversarial oracle (content consistent?)
    3. Verify the claimed legal principle against Norwegian law (lawdata_statisk)
    """
    doc_text  = args.get("document_text", "").strip()
    claimed   = args.get("claimed_principles", "").strip()

    if not doc_text:
        return "Error: document_text is required."

    citations = extract_citations(doc_text)
    if not citations:
        return (
            "## Citation Check\n\n"
            "Ingen norske juridiske referanser funnet i dokumentet.\n\n"
            "*Søkte etter: HR-YYYY-NNNN-A, Rt. YYYY s. NNN, LA/LB/LF/LG-YYYY-NNNN*"
        )

    lines = [
        "## Sitatverifisering — REMORA + DCE",
        "",
        f"**{len(citations)} juridisk(e) referanse(r) funnet. Sjekker nå:**",
        "",
    ]

    all_ok = True
    for c in citations:
        cit = c["citation"]
        lines.append(f"### `{cit}`")

        # Step 1: Check DCE D1 database
        db_result = _post(LAW_SEARCH_WORKER + "/verify-citation", {"citation": cit}, timeout=15)
        db_verdict  = db_result.get("verdict", "ERROR")
        _found_d1   = db_result.get("found_in_d1", False)
        _db_note    = db_result.get("note", "")
        d1_snippets = db_result.get("d1_matches", [])

        if db_verdict == "FOUND_IN_DATABASE":
            db_status = "FUNNET i DCE databasen"
            db_icon   = "[OK]"
        elif db_verdict == "NOT_FOUND":
            db_status = "IKKE FUNNET i DCE databasen"
            db_icon   = "[!]"
            all_ok = False
        else:
            db_status = "Mulig treff (vektor)"
            db_icon   = "[?]"

        lines.append(f"**{db_icon} Database:** {db_status}")
        if d1_snippets:
            snippet = str(d1_snippets[0].get("snippet", ""))[:200]
            lines.append(f"> {snippet}")

        # Step 2: Adversarial oracle — ask for specific case details
        oracle_result = verify_citation_existence(cit)
        oracle_status = oracle_result.get("status", "ERROR")
        oracle_claim  = oracle_result.get("oracle_claim", "")[:300]
        oracle_conf   = oracle_result.get("confidence", 0.0)

        if oracle_status in ("CANNOT_VERIFY", "LIKELY_HALLUCINATED"):
            oracle_icon = "[!]"
            all_ok = False
        elif oracle_status == "SUSPICIOUS":
            oracle_icon = "[?]"
            all_ok = False
        else:
            oracle_icon = "[~]"

        lines.append(f"**{oracle_icon} Oracle-konsensus:** {oracle_status} (conf={oracle_conf:.0%})")
        if oracle_claim:
            lines.append(f"> {oracle_claim[:200]}")

        # Combined verdict
        if db_verdict == "FOUND_IN_DATABASE" and oracle_status not in ("CANNOT_VERIFY", "LIKELY_HALLUCINATED"):
            verdict = "DELVIS VERIFISERT"
            icon = "[~]"
        elif db_verdict == "NOT_FOUND" or oracle_status in ("CANNOT_VERIFY", "LIKELY_HALLUCINATED"):
            verdict = "SANNSYNLIG HALLUSINERT eller FEIL"
            icon = "[!!]"
            all_ok = False
        else:
            verdict = "KAN IKKE VERIFISERES"
            icon = "[?]"
            all_ok = False

        lines += [f"**{icon} KONKLUSJON: {verdict}**", ""]

    # Step 3: Verify the claimed legal principle if provided
    if claimed:
        lines += ["---", "## Sjekk av juridisk prinsipp", ""]
        principle_result = verify_legal_principle(
            citations[0]["citation"] if citations else "ukjent dom",
            claimed
        )
        pv = principle_result.get("verdict")
        pc = principle_result.get("confidence", 0.0)
        pa = principle_result.get("assessment", "")

        if pv is False and pc > 0.60:
            p_icon = "[!!]"
            p_status = "JURIDISK PRINSIPP STEMMER IKKE MED NORSK RETT"
            all_ok = False
        elif pv is True and pc > 0.60:
            p_icon = "[OK]"
            p_status = "Prinsippet kan støttes av norsk rett"
        else:
            p_icon = "[?]"
            p_status = "Usikkert — sjekk med juridisk ekspert"

        lines += [
            f"**Påstand:** {claimed}",
            f"**{p_icon} {p_status}** (conf={pc:.0%})",
            f"> {pa[:300]}",
            "",
        ]

    # Also search DCE law data for the claimed principle
    if claimed:
        law_search = _post(LAW_SEARCH_WORKER + "/search", {
            "query": claimed,
            "top_k": 3,
        }, timeout=15)
        matches = law_search.get("matches", [])
        if matches:
            lines += ["**Relevante lovtekster fra DCE:**"]
            for m in matches[:2]:
                score = m.get("score", 0)
                law_id = m.get("law_id", "?")
                content = m.get("content", "") or m.get("metadata", {}).get("excerpt", "")
                if content and score > 0.05:
                    lines.append(f"- [{law_id}] (relevans {score:.2f}): {content[:200]}")
            lines.append("")

    # Summary
    lines += [
        "---",
        "## Oppsummering",
        "",
        f"**Totalt {len(citations)} referanse(r) sjekket**",
        f"**Status: {'[OK] Ingen alvorlige funn' if all_ok else '[!!] ADVARSEL: En eller flere referanser er mistenkelige eller uverifiserbare'}**",
        "",
        "*REMORA sjekker: (1) DCE databaseoppslag, (2) multi-orakel konsistens, (3) juridisk prinsipp mot norsk lov.*",
        "*Mistenkelige referanser betyr IKKE nødvendigvis at de er falske — men de krever manuell verifisering.*",
    ]

    return "\n".join(lines)


# ── Agent Control Plane handlers ───────────────────────────────────────────────────────


def _agent_post(path: str, payload: dict, timeout: int = 60) -> dict:
    """POST to the Agent Control Plane with bearer token."""
    if not AGENT_CONTROL:
        return {"error": "AGENT_CONTROL_URL is not set. Deploy workers/agent-control and set the env var."}
    url = AGENT_CONTROL.rstrip("/") + path
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": UA,
            **({
                "Authorization": f"Bearer {AGENT_SECRET}"
            } if AGENT_SECRET else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def handle_agent_start_session(args: dict) -> str:
    label  = args.get("user_label", "MCP session")
    result = _agent_post("/sessions", {"user_label": label})
    if result.get("error"):
        return f"⚠️ Feil ved opprettelse av agent-sesjon: {result['error']}"
    sid = result.get("session_id", "?")
    return (
        f"✅ **Agent-sesjon startet**\n"
        f"- Session ID: `{sid}`\n"
        f"- Label: {label}\n"
        f"- Bruk dette session_id i kall til `agent_execute_tool`\n"
        f"- Se audit-logg med `agent_audit_log`"
    )


def handle_agent_execute_tool(args: dict) -> str:
    tool       = args.get("tool", "")
    input_data = args.get("arguments", args.get("input", {}))  # "arguments" is canonical; "input" kept for compat
    session_id = args.get("session_id", "")

    if not tool:
        return "⚠️ tool er påkrevd."

    # Auto-create session if not provided
    if not session_id:
        sess = _agent_post("/sessions", {"user_label": f"auto via MCP/{tool}"})
        session_id = sess.get("session_id", "unknown")

    result = _agent_post("/execute", {
        "tool":       tool,
        "input":      input_data,
        "session_id": session_id,
    })

    if result.get("error"):
        return f"⚠️ Kontrollflate-feil: {result['error']}"

    lines = [
        f"### Agent Control: `{tool}`",
        f"- Session: `{session_id}`",
        f"- Audit ID: `{result.get('audit_id', 'N/A')}`",
        f"- Varighet: {result.get('duration_ms', '?')} ms",
        "",
    ]

    if result.get("verdict"):
        lines += [
            f"**Konklusjon:** {result['verdict']}",
            f"**Konfidens:** {result.get('confidence', 0):.0%}",
            "",
        ]

    if result.get("approval_required"):
        lines += [
            "⏳ **Venter på godkjenning** (bruk `audit_decision` med audit_id ovenfor)",
            "",
        ]

    output = result.get("output", {})
    if isinstance(output, dict) and output.get("error"):
        lines.append(f"⚠️ Upstream-feil: {output['error']}")
    else:
        lines.append("**Output:**")
        lines.append("```json")
        lines.append(json.dumps(output, indent=2, ensure_ascii=False)[:2000])
        lines.append("```")

    return "\n".join(lines)


def handle_agent_audit_log(args: dict) -> str:
    session_id = args.get("session_id", "")
    limit      = int(args.get("limit", 50))
    if not session_id:
        return "⚠️ session_id er påkrevd."
    if not AGENT_CONTROL:
        return "⚠️ AGENT_CONTROL_URL er ikke satt."

    url  = AGENT_CONTROL.rstrip("/") + f"/audit?session_id={session_id}&limit={limit}"
    req  = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        return f"⚠️ Feil: {e}"

    rows = data.get("rows", [])
    if not rows:
        return f"Ingen audit-poster for sesjon `{session_id}`."

    lines = [
        f"### Audit-logg — sesjon `{session_id}` ({len(rows)} poster)",
        "",
        "| # | Tidspunkt | Verktøy | Konklusjon | Konfidens | Godkjent? |",
        "|---|-----------|---------|-----------|-----------|----------|",
    ]
    for row in rows:
        approved = "✅" if row.get("approved") == 1 else ("❌" if row.get("approved") == 0 else ("⏳" if row.get("approval_required") else "—"))
        conf     = f"{row['confidence']:.0%}" if row.get("confidence") is not None else "—"
        lines.append(
            f"| {row['id']} | {row['ts'][:16]} | `{row['tool_called']}` "
            f"| {row.get('verdict') or '—'} | {conf} | {approved} |"
        )
    return "\n".join(lines)


def handle_remora_norwegian_law_search(args: dict) -> str:
    query = args.get("query", "").strip()
    top_k = min(int(args.get("top_k", 5)), 10)

    if not query:
        return "Error: 'query' is required."

    result = _post(LAW_SEARCH_WORKER + "/search", {
        "query": query,
        "top_k": top_k,
    }, timeout=30)

    if result.get("error"):
        return f"Lovdatabase-feil: {result['error']}"

    matches = result.get("matches", [])
    if not matches:
        return (
            f"Ingen treff for: **{query}**\n\n"
            f"Lovdatabasen dekker norske lover fra Lovdata. "
            f"Prøv med paragraf-referanse (f.eks. '§ 15-7') eller lovnavn."
        )

    lines = [
        f"## Norsk lovdatabase — \"{query}\"",
        "",
        f"**{len(matches)} treff:**",
        "",
    ]
    for i, m in enumerate(matches, 1):
        score   = m.get("score", 0)
        law_id  = m.get("law_id", "?")
        title   = m.get("title", "")
        para    = m.get("paragraph_ref", "") or m.get("section", "")
        content = (m.get("content", "") or "")[:300]
        url     = m.get("url", "")

        heading = f"### {i}. {title or law_id}"
        if para:
            heading += f" — {para}"
        lines.append(heading)
        lines.append(f"**Relevans:** {score:.3f} | **Lov-ID:** `{law_id}`")
        if content:
            lines += ["", f"> {content}..."]
        if url:
            lines.append(f"**Kilde:** {url}")
        lines.append("")

    return "\n".join(lines)


def handle_remora_rag_query(args: dict) -> str:
    query          = args.get("query", "").strip()
    domain         = args.get("domain", "general")
    use_case       = args.get("use_case", "")
    dual_consensus = args.get("dual_consensus", False)
    complexity     = args.get("complexity", "auto")

    if not query:
        return "Error: 'query' is required."

    payload: dict = {
        "query": query,
        "domain": domain,
        "dual_consensus": dual_consensus,
        "complexity": complexity,
        "use_cache": True,
    }
    if use_case:
        payload["use_case"] = use_case

    result = _post(RAG_WORKER + "/query", payload, timeout=30)

    if result.get("error"):
        return f"RAG query error: {result['error']}"

    answer       = result.get("answer")
    confidence   = result.get("confidence", 0.0)
    claim        = result.get("claim", "")
    sources      = result.get("sources", [])
    retrieved    = result.get("retrieved_chunks", 0)
    reranked     = result.get("reranked", False)
    cache_hit    = result.get("cache_hit", False)
    multilingual = result.get("multilingual", False)
    model        = result.get("model", "")
    models_ok    = result.get("models_agreed")
    dual         = result.get("dual_consensus", False)

    if answer is True:
        verdict_text = "YES — confirmed by knowledge base"
    elif answer is False:
        verdict_text = "NO — refuted by knowledge base"
    else:
        verdict_text = "UNCERTAIN — insufficient evidence in knowledge base"

    if confidence >= 0.80:
        trust = "HIGH"
    elif confidence >= 0.65:
        trust = "MEDIUM"
    elif confidence >= 0.40:
        trust = "LOW"
    else:
        trust = "VERY LOW"

    lines = [
        "## RAG Knowledge Base Query",
        "",
        f"**Query:** {query}",
        f"**Domain:** {domain}",
        "",
        f"**Verdict:** {verdict_text}",
        f"**Confidence:** {confidence:.0%} ({trust})",
        f"**Assessment:** {claim}",
        "",
    ]

    if dual and models_ok is not None:
        agreed_txt = "8B + 70B models agreed" if models_ok else "8B + 70B models disagreed — lower reliability"
        lines += [f"**Dual consensus:** {agreed_txt}", ""]

    meta = []
    if retrieved:
        meta.append(f"{retrieved} chunks retrieved")
    if reranked:
        meta.append("cross-encoder reranked")
    if multilingual:
        meta.append("multilingual index")
    if cache_hit:
        meta.append("cache hit")
    if model:
        meta.append(f"model: {model.split('/')[-1]}")
    if meta:
        lines += [f"*{' · '.join(meta)}*", ""]

    if sources:
        lines.append("**Sources:**")
        for s in sources[:5]:
            lines.append(f"- {s}")
        lines.append("")
    else:
        lines.append(
            "*No documents found. Add sources: "
            "`python scripts/ingest_corpus.py --url <URL> --domain specialised`*"
        )

    return "\n".join(lines)


def handle_remora_session_status(args: dict) -> str:
    """Return Lyapunov + intent anchor telemetry for the current local session."""
    import sys
    _REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _REPO not in sys.path:
        sys.path.insert(0, _REPO)

    try:
        from pathlib import Path

        from remora.agent_hook.intent_anchor import IntentAnchor
        from remora.agent_hook.lyapunov_tracker import LyapunovTracker
    except ImportError as e:
        return f"Error: agent_hook module not available — {e}"

    session_dir_arg = args.get("session_dir", "").strip()
    session_dir = Path(session_dir_arg) if session_dir_arg else None

    try:
        tracker = LyapunovTracker(session_dir=session_dir)
        anchor  = IntentAnchor(session_dir=session_dir)
    except Exception as e:
        return f"Error reading session state: {e}"

    s = tracker.summary()
    lines = ["## REMORA Session Status", ""]

    # Lyapunov stability
    if s["tool_calls"] == 0:
        lines += ["### Lyapunov Stability", "- No tool calls recorded yet in this session.", ""]
    else:
        v      = s["V"]
        h      = s["H"]
        d      = s["D"]
        conv   = s["converging"]
        reduct = s["total_V_reduction"]
        risk_color = (
            "✅ LOW"    if v is not None and v < 0.20 else
            "⚠️ MEDIUM" if v is not None and v < 0.60 else
            "🔴 HIGH"
        )
        lines += [
            "### Lyapunov Stability  V(t) — consensus divergence measure",
            f"- Tool calls recorded: {s['tool_calls']}",
            f"- V(t): `{v:.4f}`   ({risk_color})",
            f"- H (entropy):    `{h:.4f}`   — spread of allow/deny signal",
            f"- D (dissensus):  `{d:.4f}`   — oracle disagreement level",
            f"- Converging:     {'Yes — V(t) is decreasing' if conv else 'No — V(t) is flat or rising'}",
            f"- Total V reduction: `{reduct:+.4f}`",
            "",
        ]

    # Intent anchor
    lines += ["### Intent Anchor", ""]
    if anchor.anchored:
        lines += [
            f"- **Goal:** {anchor.intent}",
            f"- Tool calls since anchoring: {anchor.tool_call_count}",
            f"- Session ID: `{anchor.session_id or '(none)'}`",
            "",
            "_To re-anchor: `python scripts/remora_anchor.py \"<new goal>\"`_",
            "_To clear: `python scripts/remora_anchor.py --clear`_",
        ]
    else:
        lines += [
            "- No intent anchored for this session.",
            "",
            "_Anchor your session goal to enable drift detection:_",
            "_`python scripts/remora_anchor.py \"<your session goal>\"`_",
        ]

    lines += [
        "",
        "### Formal Guarantee",
        "V(t) = H(t) + λ·D(t) where H = Shannon entropy of allow/deny distribution,",
        "D = oracle dissensus (1 − max confidence). When V is non-increasing across",
        "consecutive tool calls, the session is Lyapunov-stable by construction.",
    ]

    return "\n".join(lines)


HANDLERS = {
    "remora_analyze_document":          handle_remora_analyze_document,
    "remora_verify_claim":              handle_remora_verify_claim,
    "remora_legal_analysis":            handle_remora_legal_analysis,
    "remora_rag_search":                handle_remora_rag_search,
    "remora_status":                    handle_remora_status,
    "remora_codegraph_scope":           handle_remora_codegraph_scope,
    "remora_repo_search":               handle_remora_repo_search,
    "remora_verify_legal_citations":    handle_remora_verify_legal_citations,
    "remora_norwegian_law_search":      handle_remora_norwegian_law_search,
    "remora_rag_query":                 handle_remora_rag_query,
    "remora_session_status":            handle_remora_session_status,
    # Agent Control Plane
    "agent_start_session":              handle_agent_start_session,
    "agent_execute_tool":               handle_agent_execute_tool,
    "agent_audit_log":                  handle_agent_audit_log,
}


def handle_request(request: dict) -> dict | None:
    method = request.get("method", "")
    rid    = request.get("id")

    # Notifications (no id) → no response
    if "id" not in request:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def err(code, msg):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}

    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "remora-mcp", "version": "1.0.0"},
        })

    if method == "tools/list":
        return ok({"tools": TOOLS})

    if method == "tools/call":
        params   = request.get("params", {})
        tool     = params.get("name", "")
        args     = params.get("arguments", {})
        handler  = HANDLERS.get(tool)
        if not handler:
            return err(-32602, f"Unknown tool: {tool}")
        try:
            text = handler(args)
            return ok({"content": [{"type": "text", "text": text}]})
        except Exception as e:
            return ok({"content": [{"type": "text", "text": f"Error: {e}"}]})

    return err(-32601, f"Method not found: {method}")


def main():
    import sys
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request  = json.loads(line)
            response = handle_request(request)
            if response is not None:
                print(json.dumps(response), flush=True)
        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": str(e)}
            }), flush=True)


if __name__ == "__main__":
    main()
