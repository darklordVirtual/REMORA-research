"""Knowledge Graph-ready audit log export (RDF/N-Triples).

Why RDF for AI audit trails
---------------------------
Enterprise governance requirements often call for knowledge graph
technologies (RDF/SPARQL) for governance and audit trails. RDF is the
right representation for AI decision audit logs because:

1. **Graph queries over decisions**: SPARQL lets compliance teams ask
   questions like "Show me all ESCALATE decisions in CRITICAL phase on
   Platform X in the last 30 days" — impossible to express efficiently
   in flat JSON or a relational table.

2. **Linked provenance**: Each decision triple links agent → decision →
   evidence → oracle → outcome.  This chain is traversable by any
   RDF-aware tool (Apache Jena, Oxigraph, Stardog, Amazon Neptune).

3. **AI Act compliance**: The EU AI Act (Article 12) requires high-risk
   AI systems to maintain logs that are "appropriate to the intended
   purpose."  An RDF audit graph makes those logs machine-queryable,
   not just human-readable.

RDF model
---------
Each audit record generates a cluster of triples rooted at a decision
URI::

    <https://remora.ai/decisions/{id}>
        a                          remora:Decision ;
        remora:madeByAgent         <https://remora.ai/agents/{agent_id}> ;
        remora:action              "accept" ;
        remora:phase               "ordered" ;
        remora:trustScore          "0.87"^^xsd:decimal ;
        remora:temperature         "0.14"^^xsd:decimal ;
        remora:entropy             "0.31"^^xsd:decimal ;
        remora:dissensus           "0.12"^^xsd:decimal ;
        remora:timestamp           "2026-05-28T10:00:00Z"^^xsd:dateTime ;
        remora:policyVersion       "RemoraDecisionEngine-v3" ;
        remora:question            "Is §9-6 of the HSE Act applicable?" .

    <https://remora.ai/agents/{agent_id}>
        a                          remora:Agent ;
        remora:made_decision       <https://remora.ai/decisions/{id}> .

SPARQL example queries
----------------------
Find all CRITICAL-phase decisions with trust < 0.5 in the last month::

    PREFIX remora: <https://remora.ai/ontology/>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

    SELECT ?decision ?trust ?ts WHERE {
        ?decision remora:phase "critical" .
        ?decision remora:trustScore ?trust .
        ?decision remora:timestamp ?ts .
        FILTER(?trust < "0.5"^^xsd:decimal)
        FILTER(?ts > "2026-04-28T00:00:00Z"^^xsd:dateTime)
    }

Find all escalations routed to an HSE manager::

    PREFIX remora: <https://remora.ai/ontology/>

    SELECT ?decision ?question WHERE {
        ?decision remora:action "escalate" .
        ?decision remora:recommendedRouting "hse_manager" .
        ?decision remora:question ?question .
    }

Find the full decision chain for a given agent in a session::

    PREFIX remora: <https://remora.ai/ontology/>

    SELECT ?decision ?action ?phase ?ts WHERE {
        <https://remora.ai/agents/claude-session-abc> remora:made_decision ?decision .
        ?decision remora:action ?action .
        ?decision remora:phase ?phase .
        ?decision remora:timestamp ?ts .
    } ORDER BY ?ts

Usage
-----
::

    from remora.audit.rdf_export import RDFAuditExporter, AuditRecord

    exporter = RDFAuditExporter()

    records = [
        AuditRecord(
            id="uuid-123",
            agent_id="claude-session-abc",
            action="accept",
            phase="ordered",
            trust_score=0.87,
            temperature=0.14,
            entropy=0.31,
            dissensus=0.12,
            timestamp="2026-05-28T10:00:00Z",
            policy_version="RemoraDecisionEngine-v3",
            question="Is §9-6 applicable?",
        )
    ]

    ntriples = exporter.export_ntriples(records)
    # Write to file or POST to SPARQL endpoint
    Path("audit.nt").write_text(ntriples)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# RDF namespace constants
# ---------------------------------------------------------------------------

_REMORA_ONTOLOGY = "https://remora.ai/ontology/"
_REMORA_DECISIONS = "https://remora.ai/decisions/"
_REMORA_AGENTS = "https://remora.ai/agents/"
_XSD = "http://www.w3.org/2001/XMLSchema#"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


# ---------------------------------------------------------------------------
# AuditRecord
# ---------------------------------------------------------------------------

@dataclass
class AuditRecord:
    """One REMORA decision event, ready for export to RDF.

    This mirrors the D1 audit-ledger schema in the Cloudflare worker so
    records can be pulled from D1 and fed directly into the RDF exporter.
    """

    id: str
    agent_id: str
    action: str
    timestamp: str
    policy_version: str
    question: str
    phase: str | None = None
    trust_score: float | None = None
    temperature: float | None = None
    entropy: float | None = None
    dissensus: float | None = None
    free_energy: float | None = None
    risk_estimate: float | None = None
    confidence: float | None = None
    reasons: list[str] = field(default_factory=list)
    escalation_routing: str | None = None
    audit_root: str | None = None


# ---------------------------------------------------------------------------
# N-Triples builder helpers
# ---------------------------------------------------------------------------

def _uri(value: str) -> str:
    return f"<{value}>"


def _literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _typed_literal(value: Any, xsd_type: str) -> str:
    return f'"{value}"^^<{_XSD}{xsd_type}>'


def _triple(subject: str, predicate: str, obj: str) -> str:
    return f"{subject} {predicate} {obj} ."


# ---------------------------------------------------------------------------
# RDFAuditExporter
# ---------------------------------------------------------------------------

class RDFAuditExporter:
    """Converts REMORA audit records to RDF N-Triples.

    Output is valid N-Triples (one triple per line, no Turtle prefixes).
    It can be loaded directly into any RDF store or SPARQL endpoint that
    accepts N-Triples (Oxigraph, Apache Jena, Amazon Neptune, Stardog).

    Parameters
    ----------
    base_uri:
        Custom base URI for decision and agent resources.  Defaults to
        ``https://remora.ai/``.  Override for multi-tenant deployments so
        different tenants get disjoint URI namespaces.
    """

    def __init__(self, base_uri: str = "https://remora.ai/") -> None:
        self._base = base_uri.rstrip("/") + "/"

    def _decision_uri(self, decision_id: str) -> str:
        return _uri(f"{self._base}decisions/{decision_id}")

    def _agent_uri(self, agent_id: str) -> str:
        return _uri(f"{self._base}agents/{agent_id}")

    def _pred(self, local: str) -> str:
        return _uri(f"{_REMORA_ONTOLOGY}{local}")

    def record_to_triples(self, record: AuditRecord) -> list[str]:
        """Convert one AuditRecord to a list of N-Triple strings."""
        triples: list[str] = []
        d = self._decision_uri(record.id)
        a = self._agent_uri(record.agent_id)
        pred = self._pred

        # Type assertions
        triples.append(_triple(d, _uri(_RDF_TYPE), _uri(f"{_REMORA_ONTOLOGY}Decision")))
        triples.append(_triple(a, _uri(_RDF_TYPE), _uri(f"{_REMORA_ONTOLOGY}Agent")))

        # Agent → Decision link (bidirectional for graph traversal)
        triples.append(_triple(a, pred("made_decision"), d))
        triples.append(_triple(d, pred("madeByAgent"), a))

        # Core decision attributes
        triples.append(_triple(d, pred("action"), _literal(record.action)))
        triples.append(_triple(d, pred("timestamp"), _typed_literal(record.timestamp, "dateTime")))
        triples.append(_triple(d, pred("policyVersion"), _literal(record.policy_version)))
        triples.append(_triple(d, pred("question"), _literal(record.question)))

        # Optional thermodynamic attributes
        if record.phase is not None:
            triples.append(_triple(d, pred("phase"), _literal(record.phase)))
        if record.trust_score is not None:
            triples.append(_triple(d, pred("trustScore"), _typed_literal(round(record.trust_score, 6), "decimal")))
        if record.temperature is not None:
            triples.append(_triple(d, pred("temperature"), _typed_literal(round(record.temperature, 6), "decimal")))
        if record.entropy is not None:
            triples.append(_triple(d, pred("entropy"), _typed_literal(round(record.entropy, 6), "decimal")))
        if record.dissensus is not None:
            triples.append(_triple(d, pred("dissensus"), _typed_literal(round(record.dissensus, 6), "decimal")))
        if record.free_energy is not None:
            triples.append(_triple(d, pred("freeEnergy"), _typed_literal(round(record.free_energy, 6), "decimal")))
        if record.risk_estimate is not None:
            triples.append(_triple(d, pred("riskEstimate"), _typed_literal(round(record.risk_estimate, 6), "decimal")))
        if record.confidence is not None:
            triples.append(_triple(d, pred("confidence"), _typed_literal(round(record.confidence, 6), "decimal")))
        if record.escalation_routing is not None:
            triples.append(_triple(d, pred("recommendedRouting"), _literal(record.escalation_routing)))
        if record.audit_root is not None:
            triples.append(_triple(d, pred("auditRoot"), _literal(record.audit_root)))

        # Reasons (one triple per reason)
        for reason in record.reasons:
            triples.append(_triple(d, pred("reason"), _literal(reason)))

        return triples

    def export_ntriples(self, records: list[AuditRecord]) -> str:
        """Export a list of AuditRecords as an N-Triples document."""
        lines: list[str] = [
            "# REMORA Audit Log — RDF N-Triples",
            f"# Ontology: {_REMORA_ONTOLOGY}",
            "# Validators: https://www.w3.org/TR/n-triples/",
            "",
        ]
        for record in records:
            lines.append(f"# Decision: {record.id}")
            lines.extend(self.record_to_triples(record))
            lines.append("")
        return "\n".join(lines)

    def from_decision_report(
        self,
        report: Any,
        decision_id: str,
        agent_id: str,
    ) -> AuditRecord:
        """Build an AuditRecord from a ``DecisionReport``.

        Parameters
        ----------
        report:
            A ``remora.policy.report.DecisionReport`` instance.
        decision_id:
            UUID for this decision event.
        agent_id:
            Identifier for the agent that made the decision.
        """
        obs = report.raw_observation
        F: float | None = None
        if obs.temperature is not None and obs.final_H is not None and obs.final_D is not None:
            F = 1.0 * obs.final_D - obs.temperature * obs.final_H

        return AuditRecord(
            id=decision_id,
            agent_id=agent_id,
            action=report.action.value,
            timestamp=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            policy_version=report.policy_version,
            question=obs.question,
            phase=obs.phase,
            trust_score=obs.trust_score,
            temperature=obs.temperature,
            entropy=obs.final_H,
            dissensus=obs.final_D,
            free_energy=F,
            risk_estimate=report.risk_estimate,
            confidence=report.confidence,
            reasons=[r.value for r in report.reasons],
            audit_root=report.audit_root,
        )

    @staticmethod
    def sparql_examples() -> str:
        """Return a string of useful SPARQL query examples.

        These queries work against any SPARQL 1.1 endpoint loaded with
        the N-Triples output of ``export_ntriples()``.
        """
        return """\
# ─────────────────────────────────────────────────────────────────────────────
# REMORA Audit Log — SPARQL Query Examples
# Load the .nt file into Oxigraph, Apache Jena, Amazon Neptune, or Stardog.
# ─────────────────────────────────────────────────────────────────────────────

PREFIX remora: <https://remora.ai/ontology/>
PREFIX xsd:    <http://www.w3.org/2001/XMLSchema#>

# 1. All decisions in CRITICAL phase with trust_score < 0.5
SELECT ?decision ?trust ?ts WHERE {
    ?decision remora:phase "critical" .
    ?decision remora:trustScore ?trust .
    ?decision remora:timestamp ?ts .
    FILTER(?trust < "0.5"^^xsd:decimal)
}

# 2. Count decisions by phase (thermodynamic fleet health)
SELECT ?phase (COUNT(?d) AS ?n) WHERE {
    ?d remora:phase ?phase .
} GROUP BY ?phase

# 3. All escalations routed to HSE manager
SELECT ?decision ?question ?ts WHERE {
    ?decision remora:action "escalate" .
    ?decision remora:recommendedRouting "hse_manager" .
    ?decision remora:question ?question .
    ?decision remora:timestamp ?ts .
}

# 4. Full decision chain for a specific agent (compliance audit trail)
SELECT ?decision ?action ?phase ?trust ?ts WHERE {
    <https://remora.ai/agents/claude-session-abc> remora:made_decision ?decision .
    ?decision remora:action ?action .
    OPTIONAL { ?decision remora:phase ?phase . }
    OPTIONAL { ?decision remora:trustScore ?trust . }
    ?decision remora:timestamp ?ts .
} ORDER BY ?ts

# 5. Distribution shift events (calibration alerts)
SELECT ?decision ?question ?ts WHERE {
    ?decision remora:reason "distribution_shift" .
    ?decision remora:question ?question .
    ?decision remora:timestamp ?ts .
}

# 6. Average trust score by action type (quality monitoring)
SELECT ?action (AVG(?trust) AS ?avg_trust) WHERE {
    ?d remora:action ?action .
    ?d remora:trustScore ?trust .
} GROUP BY ?action
"""
