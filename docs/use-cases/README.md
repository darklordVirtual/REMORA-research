# REMORA use cases

> ⚠️ **Illustrative, not deployment results.** REMORA is a research-grade
> governance overlay in **SHADOW_ONLY** mode — not production-certified and not
> deployed in any sector below. These are illustrative scenarios; any numbers
> are illustrative unless they link to a committed artifact in `results/` or
> `artifacts/`. REMORA governs whether a proposed **action** may proceed
> (ACCEPT / VERIFY / ABSTAIN / ESCALATE); it does not certify truth.

REMORA is **sector-agnostic**: it governs any tool-calling agent action by the
same pipeline (multi-oracle consensus → uncertainty/evidence → deterministic
policy → auditable DecisionEnvelope). The value in any sector is the same —
turn a confident-but-unverified agent action into an explicit, auditable
decision, and route the risky ones to a human. The governance semantics are
canonical in [`../reference_architecture.md`](../reference_architecture.md).

Brief illustrative scenarios:

| Sector | Governed action | What REMORA adds |
|---|---|---|
| Healthcare | AI second-opinion / triage suggestion | VERIFY/ESCALATE on low-evidence or high-risk advice before it reaches a clinician |
| Legal & compliance | Regulatory-claim assertion | Blocks confident-but-unsupported claims; routes citations to verification |
| Financial services | High-stakes decision from AI-asserted facts | Evidence-gated ACCEPT; ambiguous cases to human review |
| Energy / infrastructure | Building/grid actuation (e.g. per-zone lighting) | Deterministic hard-blocks on unsafe actuation; dry-run demonstration only |
| Security research | Vulnerability validation / disclosure | Governs report-ready vs false-positive vs escalate; see [GO-STAR integration](../integrations/gostar_integration.md) |
| Public administration | AI hallucination in legal documents | Catches fabricated citations before they enter official documents; ties to Norwegian-law verification |
| Norwegian law (MCP) | Legal research via the law-search MCP tool | Verifies citations against the Norwegian law corpus; see [MCP integration](../integrations/mcp-integration.md) |

For a concrete dry-run walkthrough of the mechanism, see
[`../reference_architecture.md`](../reference_architecture.md). Live MCP tool
behaviour is documented in [`../integrations/mcp-integration.md`](../integrations/mcp-integration.md).
