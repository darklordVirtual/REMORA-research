from remora.integrations.gostar import (
    FindingVerdict,
    GoStarBridge,
    GoStarFinding,
    GoStarScanResult,
    OracleSignal,
    Severity,
)


def test_gostar_public_api_exports():
    import remora

    assert remora.GoStarBridge is GoStarBridge
    assert remora.OracleSignal is OracleSignal
    assert remora.Severity is Severity
    assert remora.FindingVerdict is FindingVerdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal(tool: str = "semgrep", family: str = "static",
            role: str = "primary", confidence: float = 0.8) -> OracleSignal:
    return OracleSignal(tool=tool, family=family, evidence_role=role,
                        confidence=confidence, result={"match": True})


def _finding(
    fid: str = "F-001",
    severity: Severity = Severity.HIGH,
    signals: list[OracleSignal] | None = None,
) -> GoStarFinding:
    return GoStarFinding(
        finding_id=fid,
        title="SQL injection in login handler",
        description="User input flows unsanitised into SQL query",
        severity=severity,
        cwe="CWE-89",
        file_path="app/auth.py",
        symbol="login()",
        source="request.form['username']",
        sink="cursor.execute()",
        oracle_signals=signals or [],
    )


# ---------------------------------------------------------------------------
# GoStarFinding
# ---------------------------------------------------------------------------

class TestGoStarFinding:
    def test_content_hash_deterministic(self):
        f1 = _finding()
        f2 = _finding()
        assert f1.content_hash() == f2.content_hash()

    def test_content_hash_differs_on_id(self):
        f1 = _finding(fid="F-001")
        f2 = _finding(fid="F-002")
        assert f1.content_hash() != f2.content_hash()


# ---------------------------------------------------------------------------
# Local evidence fusion
# ---------------------------------------------------------------------------

class TestLocalFusion:
    def test_no_signals_returns_uncertain(self):
        bridge = GoStarBridge()
        result = bridge.fuse(_finding(signals=[]))
        assert result.verdict is None
        assert result.confidence == 0.0
        assert result.signals_used == 0

    def test_single_primary_high_confidence(self):
        bridge = GoStarBridge()
        result = bridge.fuse(_finding(signals=[_signal(confidence=0.9)]))
        assert result.verdict is True
        assert result.confidence >= 0.7
        assert result.signals_used == 1

    def test_contradicting_signal_lowers_confidence(self):
        bridge = GoStarBridge()
        signals = [
            _signal(confidence=0.3),
            _signal(tool="osv", role="contradicting", confidence=0.8),
        ]
        result = bridge.fuse(_finding(signals=signals))
        # With contradiction, confidence should be lower
        assert result.confidence < 0.7

    def test_multiple_corroborating_signals(self):
        bridge = GoStarBridge()
        signals = [
            _signal(tool="semgrep", role="primary", confidence=0.8),
            _signal(tool="codegraph", role="corroborating", confidence=0.7),
            _signal(tool="osv", role="corroborating", confidence=0.6),
        ]
        result = bridge.fuse(_finding(signals=signals))
        assert result.verdict is True
        assert result.oracle_agreement == 1.0  # all support
        assert result.signals_used == 3

    def test_provenance_hash_nonempty(self):
        bridge = GoStarBridge()
        result = bridge.fuse(_finding(signals=[_signal()]))
        assert len(result.provenance_hash) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# Governance decisions
# ---------------------------------------------------------------------------

class TestGovernance:
    def test_critical_uncertain_escalates(self):
        bridge = GoStarBridge()
        finding = _finding(severity=Severity.CRITICAL, signals=[])
        result = bridge.govern(finding)
        assert result.verdict == FindingVerdict.ESCALATE
        assert result.governance_action == "ESCALATE"
        assert result.risk_tier == "critical"

    def test_high_confirmed_report_ready(self):
        bridge = GoStarBridge()
        signals = [
            _signal(tool="semgrep", role="primary", confidence=0.9),
            _signal(tool="taint", role="corroborating", confidence=0.85),
        ]
        finding = _finding(severity=Severity.HIGH, signals=signals)
        result = bridge.govern(finding)
        assert result.verdict == FindingVerdict.REPORT_READY
        assert result.governance_action == "VERIFY"  # high severity → VERIFY not ACCEPT

    def test_low_confirmed_accepted(self):
        bridge = GoStarBridge()
        signals = [
            _signal(role="primary", confidence=0.9),
            _signal(tool="osv", role="corroborating", confidence=0.8),
        ]
        finding = _finding(severity=Severity.LOW, signals=signals)
        result = bridge.govern(finding)
        assert result.verdict == FindingVerdict.REPORT_READY
        assert result.governance_action == "ACCEPT"

    def test_single_signal_needs_corroboration(self):
        bridge = GoStarBridge(require_corroboration=True)
        signals = [_signal(confidence=0.95)]
        finding = _finding(severity=Severity.MEDIUM, signals=signals)
        result = bridge.govern(finding)
        assert result.verdict == FindingVerdict.NEEDS_REVIEW
        assert result.governance_action == "VERIFY"

    def test_false_positive_detection(self):
        bridge = GoStarBridge(fp_threshold=0.35)
        signals = [
            _signal(role="primary", confidence=0.1),
            _signal(tool="osv", role="contradicting", confidence=0.9),
        ]
        finding = _finding(severity=Severity.LOW, signals=signals)
        result = bridge.govern(finding)
        assert result.verdict == FindingVerdict.FALSE_POSITIVE
        assert result.governance_action == "ACCEPT"

    def test_envelope_hash_present(self):
        bridge = GoStarBridge()
        result = bridge.govern(_finding(signals=[_signal()]))
        assert len(result.envelope_hash) == 64

    def test_history_accumulates(self):
        bridge = GoStarBridge()
        bridge.govern(_finding(fid="F-1", signals=[_signal()]))
        bridge.govern(_finding(fid="F-2", signals=[_signal()]))
        assert len(bridge.history) == 2

    def test_uncertain_high_risk_needs_review(self):
        bridge = GoStarBridge()
        signals = [
            _signal(role="primary", confidence=0.5),
            _signal(tool="osv", role="contradicting", confidence=0.4),
        ]
        finding = _finding(severity=Severity.HIGH, signals=signals)
        result = bridge.govern(finding)
        assert result.verdict == FindingVerdict.NEEDS_REVIEW
        assert result.governance_action == "VERIFY"


# ---------------------------------------------------------------------------
# Scan-level governance
# ---------------------------------------------------------------------------

class TestScanGovernance:
    def test_govern_scan_processes_all(self):
        bridge = GoStarBridge()
        scan = GoStarScanResult(
            repo="example/repo",
            findings=[
                _finding(fid="F-1", severity=Severity.CRITICAL, signals=[]),
                _finding(fid="F-2", severity=Severity.LOW, signals=[_signal(), _signal(tool="osv", role="corroborating")]),
            ],
            tools_used=["semgrep", "osv"],
        )
        results = bridge.govern_scan(scan)
        assert len(results) == 2
        assert results[0].verdict == FindingVerdict.ESCALATE  # critical + no signals
        assert results[1].verdict == FindingVerdict.REPORT_READY  # low + confirmed


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

class TestSummary:
    def test_empty_summary(self):
        bridge = GoStarBridge()
        assert bridge.summary() == {"total": 0}

    def test_summary_counts(self):
        bridge = GoStarBridge()
        bridge.govern(_finding(fid="F-1", severity=Severity.CRITICAL, signals=[]))
        bridge.govern(_finding(fid="F-2", severity=Severity.LOW,
                               signals=[_signal(), _signal(tool="osv", role="corroborating")]))
        s = bridge.summary()
        assert s["total"] == 2
        assert s["escalated"] >= 1
        assert "mean_confidence" in s


# ---------------------------------------------------------------------------
# MCP fusion (mock)
# ---------------------------------------------------------------------------

class _MockMCPClient:
    def __init__(self, response: dict):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, tool_name: str, args: dict) -> dict:
        self.calls.append((tool_name, args))
        return self._response


class TestMCPFusion:
    def test_mcp_fusion_called(self):
        mock = _MockMCPClient({"verdict": True, "confidence": 0.85,
                                "oracle_agreement": 0.9, "reasoning": "confirmed",
                                "provenance_hash": "abc123"})
        bridge = GoStarBridge(mcp_client=mock)
        result = bridge.fuse(_finding(signals=[_signal()]))
        assert result.verdict is True
        assert result.confidence == 0.85
        assert len(mock.calls) == 1
        assert mock.calls[0][0] == "remora_evidence_fusion"

    def test_mcp_failure_returns_uncertain(self):
        class FailingMCP:
            def call_tool(self, *a, **kw):
                raise ConnectionError("MCP down")

        bridge = GoStarBridge(mcp_client=FailingMCP())
        result = bridge.fuse(_finding(signals=[_signal()]))
        assert result.verdict is None
        assert result.confidence == 0.0
        assert "MCP fusion failed" in result.reasoning

    def test_mcp_null_verdict(self):
        mock = _MockMCPClient({"verdict": None, "confidence": 0.4})
        bridge = GoStarBridge(mcp_client=mock)
        result = bridge.fuse(_finding(signals=[_signal()]))
        assert result.verdict is None


# ---------------------------------------------------------------------------
# SecurityGovernanceResult serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict_keys(self):
        bridge = GoStarBridge()
        result = bridge.govern(_finding(signals=[_signal()]))
        d = result.to_dict()
        expected_keys = {"finding_id", "verdict", "governance_action",
                         "risk_tier", "confidence", "fusion_confidence",
                         "reasoning", "envelope_hash", "timestamp"}
        assert set(d.keys()) == expected_keys

    def test_to_dict_values_correct(self):
        bridge = GoStarBridge()
        result = bridge.govern(_finding(fid="F-99", signals=[_signal()]))
        d = result.to_dict()
        assert d["finding_id"] == "F-99"
        assert d["governance_action"] in ("ACCEPT", "VERIFY", "ABSTAIN", "ESCALATE")
