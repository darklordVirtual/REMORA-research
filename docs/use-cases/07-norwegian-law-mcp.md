# Norwegian Law — Verified Legal Research via MCP

> ⚠️ **Scope: illustrative scenario, not a deployment result.** REMORA is a
> research-grade governance overlay in **SHADOW_ONLY** mode — it is not
> production-certified and has not been deployed in the sector below. The
> walkthrough and any numbers in it are **illustrative** unless they link to a
> committed artifact in `results/` or `artifacts/`; they are not measured
> outcomes. REMORA governs whether a proposed **action** may proceed
> (ACCEPT/VERIFY/ABSTAIN/ESCALATE); it does not certify truth and is not a
> fact-checker. **ETR** ("Effective Truth Rate" — `remora/scoring.py`) is an *illustrative* narrative
> score in these documents only — it is **not** one of REMORA's canonical
> outputs and appears in no claim in `docs/assurance/claim_register_v1.yaml`.
> See the [claim register](../assurance/claim_register_v1.yaml) and
> [evidence summary](../02-evidence-and-claims.md) for governed claims.

> **Who this is for:** Lawyers, compliance officers, public sector employees,
> and anyone who needs to verify Norwegian legal claims or citations using AI.

---

## The scenario

A user is working in Claude Desktop. They receive a legal document — a debt
collection notice, a contract, or a public administration memo — and want to
know whether it cites real Norwegian law, and whether the legal claims hold up.

Without leaving the AI assistant, they can run a three-step verification:

1. Check whether cited court decisions actually exist (`remora_verify_legal_citations`)
2. Look up the specific law section in the Norwegian statute corpus (`remora_norwegian_law_search`)
3. Get a multi-oracle legal analysis of the document (`remora_legal_analysis`)

---

## System context: REMORA and DCE

**REMORA** (this repository) is an open-source governance overlay for AI-agent actions; its multi-oracle consensus is one input to that governance, not the product itself.
Its MCP server (`servers/mcp_remora.py`) exposes tools that Claude can call.
REMORA's Cloudflare Workers provide: consensus scoring, RAG synthesis,
and a law-search bridge.

**DCE** (Document Compliance Engine / Mine Dokumenter) is a separate, closed-source
Norwegian document intelligence platform. It is not part of this repository.

DCE maintains a private knowledge base of Norwegian legal data:
- **Norwegian statute law** — all current regulations, semantically indexed
  with multilingual embeddings (bge-m3, 1024-dim) in a Cloudflare Vectorize index
- **Legal intelligence** — Høyesterett (Supreme Court) decisions, Finansklagenemnda
  complaints, Datatilsynet decisions, Finanstilsynet supervision cases, parliamentary
  preparatory works (forarbeider), and NPE patient injury cases

The law-search bridge (`workers/law-search/`) connects REMORA to DCE's private
Cloudflare infrastructure. The bridge source code is open; the data behind it is not.

> **To access DCE data for your own REMORA deployment:**
> contact support@luftfiber.no

---

## Live demonstration: debt collection notice

The following shows what happens when all three MCP tools run on a real example.

### Document received

```
Inkassovarsel. Vi krever herved betalt kr 12.450 for faktura nr 2024-881.
Betalingsfristen er overskredet med 45 dager.
Inkassosalæret er satt til kr 700.
Dersom betaling ikke skjer innen 14 dager vil vi ta ut stevning.
Kravet er på vegne av Elkjøp Norge AS.
```

---

### Step 1 — `remora_verify_legal_citations`

Extracts citations from the document and checks each against the DCE knowledge base.

```
Tool call: remora_verify_legal_citations({
  "document_text": "<document above>",
  "jurisdiction": "Norway"
})

Result: No explicit court citations found in this document.
```

No fabricated case references — this is a clean document.

---

### Step 2 — `remora_norwegian_law_search`

Looks up what Norwegian law says about the relevant topic.

```
Tool call: remora_norwegian_law_search({
  "query": "inkassosalær maksimalsatser inkassoforskriften",
  "top_k": 3
})

1. Lov om inkassovirksomhet (inkassoloven) § 10  score=0.673
   "Når et krav er mottatt til inkasso og betalingsfristen i inkassovarselet
    er utløpt uten at betaling er skjedd, kan inkassator kreve inkassosalær ..."

2. Inkassoforskriften § 2-2  score=0.641
   "Inkassosalæret kan ikke overstige de til enhver tid fastsatte maksimalsatser ..."

3. Finansklagenemnda — Om nemndas kompetanse  score=0.670
   "... plikter å betale blant annet gebyrer ..."
```

The statute corpus confirms there are regulated maximum rates for debt collection fees.

---

### Step 3 — `remora_legal_analysis`

Combines RAG retrieval with three-oracle consensus to assess the legal question.

```
Tool call: remora_legal_analysis({
  "document_text": "<document above>",
  "analysis_question": "Is the debt collection fee of NOK 700 lawful under the Norwegian Debt Collection Act?",
  "jurisdiction": "Norway"
})

Verdict: YES
Confidence: 100 %  (HIGH)
Assessment: The debt collection fee of NOK 700 and the notice are lawfully formed
            under the Norwegian Debt Collection Act (inkassoloven).
Consensus: REMORA[general] YES conf=1.00 (6/3, 3iter)
```

The fee is within the regulated maximum. The notice is lawfully formed.

---

## Tool coverage summary

| Tool | Extension needed | What it checks |
|------|:---:|----------------|
| `remora_verify_legal_citations` | DCE | Whether cited court decisions exist in Norwegian legal databases |
| `remora_norwegian_law_search` | DCE | Authoritative statute text from the Norwegian law corpus |
| `remora_legal_analysis` | None | Multi-oracle consensus on a legal question (REMORA core + RAG KB) |
| `remora_verify_claim` | None | Quick true/false on a specific legal claim |

Tools marked **DCE** connect to the closed-source DCE knowledge base.
Tools marked **None** run on REMORA's open-source core workers only.

---

## Citation detection: the Asker case

The most important use of `remora_verify_legal_citations` is detecting
AI-hallucinated court decisions before they enter formal documents.

In April 2026, Asker municipality passed a formal eviction decision (vedtak)
to remove land occupants (husokkupanter) from Hurummarka. An AI tool was used
during document preparation to find legal precedents. The AI fabricated three
Supreme Court decisions that do not exist:
`HR-2015-2386-A`, `HR-2014-2288-A`, `HR-2020-2135-A`.
The citations were included in the official decision. When police were asked
to enforce the eviction, they found that none of the cited cases exist.
Police refused to act.

All three look plausible. All three fail the DCE knowledge base lookup:

```
remora_verify_legal_citations({
  "document_text": "... HR-2015-2386-A ... HR-2014-2288-A ... HR-2020-2135-A ..."
})

→ HR-2015-2386-A  NOT FOUND  CANNOT_VERIFY  → [!!] LIKELY HALLUCINATED
→ HR-2014-2288-A  NOT FOUND  CANNOT_VERIFY  → [!!] LIKELY HALLUCINATED
→ HR-2020-2135-A  NOT FOUND  CANNOT_VERIFY  → [!!] LIKELY HALLUCINATED

STATUS: WARNING — one or more citations are suspicious or unverifiable
```

The parametric LLMs alone confirm all three as valid with 100 % confidence —
because they pattern-match the citation format from training data.
**Only the deterministic database lookup catches the hallucination.**

Full documented analysis: [06-public-administration-hallucination.md](06-public-administration-hallucination.md)

---

## What REMORA cannot do

- `remora_norwegian_law_search` returns statute text from the DCE index.
  The DCE index covers current regulations. Historical versions and repealed
  laws may not be present.
- `remora_verify_legal_citations` checks whether a citation appears in the
  DCE knowledge base. Absence from DCE does not mean the citation is fake —
  it means it could not be verified here. **Always confirm at lovdata.no
  for binding conclusions.**
- The three-oracle legal analysis (`remora_legal_analysis`) uses general-purpose
  language models that are not lawyers. For binding legal advice, consult a
  qualified attorney.

---

## Technical reference

- MCP server: `servers/mcp_remora.py`
- Law-search bridge: `workers/law-search/src/index.ts`
- MCP integration guide: [`docs/mcp-integration.md`](../mcp-integration.md)
- Full public administration case: [`docs/use-cases/06-public-administration-hallucination.md`](06-public-administration-hallucination.md)
