---
id: w3c_prov_summary
title: W3C PROV — Provenance Model for REMORA DecisionEnvelope
source: W3C PROV-DM, PROV-O, PROV-N
source_url: https://www.w3.org/TR/prov-overview/
version_or_accessed_date: W3C Recommendation April 2013 (stable)
license_note: W3C Document License — free to use with attribution
intended_use: Audit trail design, DecisionEnvelope provenance mapping
---

## 1. What this source says

W3C PROV defines a model for representing provenance — information about the history
and origin of data and processes. Core concepts:

- **Entity**: A physical or digital thing (e.g., an agent action, a decision)
- **Activity**: Something that occurs over time (e.g., a policy evaluation)
- **Agent**: A thing with responsibility (e.g., an AI agent, a human reviewer)
- **wasGeneratedBy**: Entity produced by Activity
- **wasAssociatedWith**: Activity linked to Agent
- **wasDerivedFrom**: Entity derived from another Entity
- **wasInfluencedBy**: Causal attribution chain

## 2. Why it matters for REMORA

The DecisionEnvelope directly implements PROV concepts:
- RequestBlock = Entity (proposed action)
- AssessmentBlock = Activity (policy evaluation)
- GateBlock = Entity (decision output) wasGeneratedBy AssessmentBlock
- AuditBlock = provenance record with hash chain

The RemoraAuditChain implements PROV's chain-of-custody: each entry
`wasDerivedFrom` the previous, linked by SHA-256 hash.

## 3. Gate rules derived from this source

| Condition | Gate | Rationale |
|-----------|------|-----------|
| Missing provenance/audit fields | VERIFY | Cannot establish accountability |
| assurance_root not set on critical action | VERIFY | Chain of custody broken |
| previous_hash null on non-genesis entry | VERIFY | Hash chain integrity suspect |

## 4. Evidence fields REMORA should require

- `assurance_root`: hash linking to originating evidence
- `audit.hash`: SHA-256 commitment to this decision
- `audit.previous_hash`: chain linkage to prior decision
- `request_id`: unique identifier for PROV Entity

## 5. Example scenarios

- Critical infrastructure action with no audit trail → VERIFY
- Decision with broken hash chain → ESCALATE (integrity violation)
- Read-only action with full PROV trail → ACCEPT

## 6. Limitations / do-not-overclaim notes

REMORA's audit chain is SHA-256 based, not a full PROV-O RDF graph.
The current implementation does not export PROV-N or PROV-O serializations.
This is a future extension, not a current capability.
