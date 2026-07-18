# REMORA Knowledge Dataset v1

Curated, reproducible knowledge and benchmark dataset for the REMORA governance overlay.

## Purpose

This dataset provides:
- **100 labelled agent-action scenarios** with expected gate decisions
- **Curated static RAG**, policy summaries agents can retrieve at decision time
- **Evidence packs**, 27 structured evidence objects covering 6 domains
- **Shadow replay log**, 100 entries for counterfactual governance analysis
- **Live feed ingesters**, NVD, EPSS, CISA KEV, MITRE ATT&CK
- **Policy YAML + Rego**, machine-readable gate rules and risk-tier definitions
- **Learning examples**, reviewer outcome patterns and policy update candidates

## Critical Policy Constraint

> **Policy candidates are never auto-applied.**  
> REMORA may propose policy improvements based on reviewer outcomes, but every policy update requires **explicit human/policy-owner approval** and passing regression tests before `gate_rules.yaml` is modified.  
> See `learning/policy_update_candidates.example.jsonl` for the full workflow.

---

## Directory Structure

```
remora_knowledge_v1/
├── static_rag/                    # Curated markdown knowledge for RAG retrieval
│   ├── ai_governance/
│   │   └── nist_ai_rmf_summary.md
│   ├── agent_security/
│   │   └── owasp_llm_top10_policy_map.md
│   ├── audit_provenance/
│   │   └── w3c_prov_summary.md
│   ├── kubernetes_iac/
│   │   └── kubernetes_admission_control_summary.md
│   └── grid_operations/
│       └── grid_ai_operations_summary.md
│
├── policies/                      # Machine-readable gate rules
│   ├── remora_gate_rules.yaml     # 12 gate rules (GATE-001..012)
│   ├── risk_tier_mapping.yaml     # low/medium/high/critical definitions
│   ├── evidence_requirements.yaml # Required evidence per gate
│   └── rego_examples/
│       └── remora_action_gate.rego
│
├── scenarios/
│   └── agent_action_scenarios.jsonl   # 100 labelled scenarios
│
├── expected_decisions/
│   └── expected_gate_decisions.jsonl  # 100 expected outcomes
│
├── evidence_packs/
│   └── evidence_objects.jsonl         # 27 structured evidence objects
│
├── replay_logs/
│   └── shadow_replay_demo.jsonl       # 100 shadow replay entries
│
├── live_feeds/                    # Directories for live-ingested data
│   ├── nvd/
│   ├── epss/
│   ├── cisa_kev/
│   └── mitre_attack/
│
├── learning/                      # Policy learning examples (read-only, not auto-applied)
│   ├── reviewer_outcomes.example.jsonl
│   └── policy_update_candidates.example.jsonl
│
└── scripts/
    ├── ingest_nvd.py
    ├── ingest_epss.py
    ├── ingest_cisa_kev.py
    ├── ingest_mitre_attack.py
    └── validate_knowledge_dataset.py
```

---

## Scenario Schema

Each line in `agent_action_scenarios.jsonl`:

| Field | Type | Description |
|-------|------|-------------|
| `scenario_id` | str | Unique identifier |
| `domain` | str | e.g. `kubernetes`, `ai_governance`, `finance` |
| `risk_tier` | str | `low` / `medium` / `high` / `critical` |
| `action_type` | str | e.g. `destructive_write`, `read`, `deploy` |
| `target_environment` | str | `production`, `staging`, `development` |
| `proposed_action` | str | Natural-language description |
| `tool_name` | str | Simulated tool name |
| `tool_args` | object | Simulated tool arguments |
| `expected_decision` | str | `accept` / `verify` / `abstain` / `escalate` |
| `acceptable_alternatives` | list | Other valid outcomes |
| `must_not` | list | Outcomes that would be a policy violation |
| `unsafe` | bool | Whether the action is inherently unsafe |
| `policy_violation` | bool | Whether action violates a gate rule |
| `evidence_required` | list | Required evidence types |
| `reason_tags` | list | Why this decision was assigned |

---

## Evidence Object Schema

Each line in `evidence_objects.jsonl`:

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `evidence_id` | str |, | Unique identifier |
| `source` | str |, | Originating authority (NIST, CISA, etc.) |
| `title` | str |, | Human-readable title |
| `content` | str |, | Substantive evidence text |
| `domain` | str |, | Primary domain |
| `risk_tags` | list |, | Risk vocabulary tags |
| `authority_score` | float | [0,1] | Source authority weight |
| `freshness_score` | float | [0,1] | How current the evidence is |
| `coverage_score` | float | [0,1] | Breadth of coverage |
| `contradiction_score` | float | [0,1] | Internal contradiction estimate |

---

## Gate Rules Summary

Defined in `policies/remora_gate_rules.yaml`:

| Rule ID | Name | Action |
|---------|------|--------|
| GATE-001 | critical_destructive_write | ESCALATE |
| GATE-002 | prompt_injection_detected | ESCALATE |
| GATE-003 | k8s_privileged_pod | ESCALATE |
| GATE-004 | excessive_agency | ESCALATE |
| GATE-005 | kev_cve_present | ESCALATE |
| GATE-006 | public_exposure_critical | ESCALATE |
| GATE-007 | read_only_accept | ACCEPT |
| GATE-008 | grid_switching | ESCALATE |
| GATE-009 | grid_load_shedding | ESCALATE |
| GATE-010 | missing_audit_trail | ABSTAIN |
| GATE-011 | terraform_destroy | VERIFY |
| GATE-012 | dry_run_accept | ACCEPT |

---

## Decision Distribution (100 scenarios)

| Decision | Count | % |
|----------|-------|---|
| ESCALATE | ~35 | 35% |
| VERIFY | ~30 | 30% |
| ACCEPT | ~25 | 25% |
| ABSTAIN | ~10 | 10% |

---

## Usage

### Run validation

```bash
python datasets/remora_knowledge_v1/scripts/validate_knowledge_dataset.py
```

### Run shadow replay

```bash
make shadow-replay-knowledge
# or:
python scripts/shadow_replay.py \
  --input datasets/remora_knowledge_v1/replay_logs/shadow_replay_demo.jsonl
```

### Ingest live feeds

```bash
make ingest-live-feeds
# or individually:
python datasets/remora_knowledge_v1/scripts/ingest_cisa_kev.py --dry-run
python datasets/remora_knowledge_v1/scripts/ingest_nvd.py --kev --dry-run
python datasets/remora_knowledge_v1/scripts/ingest_epss.py --epss-gt 0.7 --dry-run
python datasets/remora_knowledge_v1/scripts/ingest_mitre_attack.py --domain enterprise --dry-run
```

### Use StaticJsonlEvidenceProvider

```python
from remora.evidence import StaticJsonlEvidenceProvider

provider = StaticJsonlEvidenceProvider()
result = provider.fetch(
    question="Should agent execute kubectl delete namespace prod?",
    domain="kubernetes",
    risk_tier="critical",
    action_type="destructive_write",
    target_environment="production",
    oracle_responses=[],
)
print(result.signal.evidence_strength)   # e.g. 0.823
print(result.signal_source)             # retrieval_static_jsonl
```

---

## Invariants

The dataset satisfies these structural invariants (verified by `validate_knowledge_dataset.py`):

1. Every scenario has a corresponding expected_decision
2. Every expected_decision references a known scenario
3. Evidence objects have all required fields with valid types
4. No high/critical destructive action has expected_decision = ACCEPT
5. All four outcomes (accept/verify/abstain/escalate) are represented
6. All numeric scores are in range [0, 1]
7. No duplicate scenario_ids or evidence_ids
8. Replay log entries reference known scenario_ids
9. Gate rules YAML parses; each rule has required keys
10. Risk-tier mapping defines all four tiers

---

## Sources

| Domain | Primary Sources |
|--------|----------------|
| AI Governance | NIST AI RMF (NIST AI 100-1), NIST AI 600-1 |
| Agent Security | OWASP LLM Top 10 (2025) |
| Audit/Provenance | W3C PROV-DM, W3C PROV-O |
| Kubernetes/IaC | K8s Admission Control docs, CIS Benchmarks |
| Grid Operations | NERC CIP standards, IEC 62351 |
| Vulnerabilities | NVD (NIST), CISA KEV, FIRST EPSS, MITRE ATT&CK |

---

## License

Dataset content is Apache-2.0-licensed (same as REMORA).
Third-party source summaries are derived works for research purposes.  
MITRE ATT&CK® is a trademark of The MITRE Corporation.  
NIST publications are in the public domain.
