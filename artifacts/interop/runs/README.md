# Interop run records

One file per run, in the shape of
[`interop-result-v1`](../schemas/interop-result-v1.schema.json). A record
names the contract, the claim, the exact bytes evaluated (`fixture.digest`
and `fixture.package_digest`), who evaluated them, at which independence
level, and what the result does and does not establish. The status is one
field of many.

`scripts/interop_author_run.py --write` produces the author records
(`*-author-L0.json`): REMORA's own evaluator and the reference verifier, run
by the producer. They are `L0_SELF_TEST` and advance no contract.
`scripts/interop_author_run.py --check` re-runs them and refuses a record
whose results or digests no longer match the committed package.

An external record is added by the verifier's pull request, named
`<contract>-<verifier>-<level>.json`, and is reviewed under the policy in the
contract's `verifier-request.json`. `scripts/interop_package.py --check`
validates every record here against the schema and against the bytes it
names, and `scripts/build_interop_matrix.py` derives
[`docs/interop/INTEROP_MATRIX.md`](../../../docs/interop/INTEROP_MATRIX.md)
from them. Nothing in this directory is read by policy, enforcement or
execution code.
