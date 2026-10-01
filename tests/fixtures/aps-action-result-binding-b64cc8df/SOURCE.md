# Pinned APS action-result-binding inputs

Upstream: https://github.com/Agent-Authority-Conformance/aps-conformance-suite

Commit: `b64cc8dfa889b493bbf285fbb115a988ac54566b`.

`chain.json` and `vectors.json` are byte-for-byte copies of
`fixtures/action-result-binding/` at that commit. Copyright 2026 Tymofii
Pidlisnyi; Apache-2.0. The upstream license is included as `LICENSE`.

SHA-256:

| File | Digest |
|---|---|
| chain.json | 93415285378cd2241476ab94114c50dec85b330bb8c0b1f6c75d252274b0432a |
| vectors.json | 1cbad25150e4779ef067e269329b0954b966898d6ca933a98b2e3949b23d117b |

The regression calls REMORA's existing `receipt_decision_ref` and
`classify_receipt_decision_relation`. No APS SDK or sibling clone is needed.
These are digest/relation tests, not a new action-result verifier.

The four upstream expectation blocks remain separate. `sdk_ts` and `sdk_py`
are recorded expectations; the actual run logs are in
`artifacts/interop/aps-b64cc8df-action-result-binding/`. `replay_policy` is
derived from stated rules, not an Agent Replay execution result.
