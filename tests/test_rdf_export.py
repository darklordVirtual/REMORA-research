"""Tests for the Knowledge Graph RDF audit log exporter."""
from __future__ import annotations


from remora.audit.rdf_export import AuditRecord, RDFAuditExporter


def _sample_record(**kwargs) -> AuditRecord:
    defaults = dict(
        id="uuid-123",
        agent_id="claude-session-abc",
        action="accept",
        timestamp="2026-05-28T10:00:00Z",
        policy_version="RemoraDecisionEngine-v3",
        question="Is §9-6 of the HSE Act applicable?",
        phase="ordered",
        trust_score=0.87,
        temperature=0.14,
        entropy=0.31,
        dissensus=0.12,
        free_energy=-0.042,
        risk_estimate=0.13,
        confidence=0.87,
        reasons=["ordered_high_trust"],
    )
    defaults.update(kwargs)
    return AuditRecord(**defaults)


class TestRDFAuditExporter:
    def test_record_to_triples_returns_list_of_strings(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record()
        triples = exporter.record_to_triples(record)
        assert isinstance(triples, list)
        assert all(isinstance(t, str) for t in triples)

    def test_triples_end_with_dot(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record()
        for triple in exporter.record_to_triples(record):
            assert triple.endswith(" ."), f"Triple missing dot: {triple!r}"

    def test_decision_uri_present(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record(id="uuid-999")
        triples = exporter.record_to_triples(record)
        combined = "\n".join(triples)
        assert "uuid-999" in combined

    def test_agent_uri_present(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record(agent_id="my-agent-session")
        triples = exporter.record_to_triples(record)
        combined = "\n".join(triples)
        assert "my-agent-session" in combined

    def test_action_triple_present(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record(action="escalate")
        triples = exporter.record_to_triples(record)
        combined = "\n".join(triples)
        assert '"escalate"' in combined

    def test_phase_triple_present(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record(phase="critical")
        triples = exporter.record_to_triples(record)
        combined = "\n".join(triples)
        assert '"critical"' in combined

    def test_trust_score_typed_literal(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record(trust_score=0.87)
        triples = exporter.record_to_triples(record)
        combined = "\n".join(triples)
        assert "xsd:decimal" in combined or "XMLSchema#decimal" in combined

    def test_none_fields_omitted(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record(phase=None, trust_score=None, temperature=None)
        triples = exporter.record_to_triples(record)
        combined = "\n".join(triples)
        assert "remora:phase" not in combined
        assert "remora:trustScore" not in combined

    def test_reasons_produce_multiple_triples(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record(reasons=["ordered_high_trust", "trace_attached"])
        triples = exporter.record_to_triples(record)
        reason_triples = [t for t in triples if "reason" in t and "ordered_high_trust" in t or
                                                "reason" in t and "trace_attached" in t]
        assert len(reason_triples) == 2

    def test_bidirectional_agent_decision_link(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record()
        triples = exporter.record_to_triples(record)
        combined = "\n".join(triples)
        assert "made_decision" in combined
        assert "madeByAgent" in combined

    def test_export_ntriples_valid_format(self) -> None:
        exporter = RDFAuditExporter()
        records = [_sample_record(), _sample_record(id="uuid-456", agent_id="agent-2")]
        output = exporter.export_ntriples(records)
        assert isinstance(output, str)
        assert "uuid-123" in output
        assert "uuid-456" in output
        # Every non-comment non-blank line must end with space+dot
        for line in output.splitlines():
            if line and not line.startswith("#"):
                assert line.endswith(" ."), f"Bad triple line: {line!r}"

    def test_custom_base_uri(self) -> None:
        exporter = RDFAuditExporter(base_uri="https://aker-bp.ai/audit/")
        record = _sample_record()
        triples = exporter.record_to_triples(record)
        combined = "\n".join(triples)
        assert "aker-bp.ai" in combined

    def test_question_text_escaped(self) -> None:
        exporter = RDFAuditExporter()
        record = _sample_record(question='He said "hello" and left.')
        triples = exporter.record_to_triples(record)
        combined = "\n".join(triples)
        assert '\\"hello\\"' in combined

    def test_sparql_examples_is_string(self) -> None:
        examples = RDFAuditExporter.sparql_examples()
        assert isinstance(examples, str)
        assert "SELECT" in examples
        assert "remora:" in examples

    def test_from_decision_report_builds_record(self) -> None:
        from remora.policy.decision_engine import RemoraDecisionEngine
        from remora.policy.observation import PolicyObservation

        obs = PolicyObservation(
            question="Is §9-6 applicable?",
            phase="ordered",
            trust_score=0.87,
            temperature=0.14,
            final_H=0.31,
            final_D=0.12,
        )
        engine = RemoraDecisionEngine(conformal_trust_threshold=0.72)
        report = engine.decide(obs)
        exporter = RDFAuditExporter()
        record = exporter.from_decision_report(report, "uuid-test", "agent-test")
        assert record.agent_id == "agent-test"
        assert record.question == "Is §9-6 applicable?"
        assert record.action == report.action.value
