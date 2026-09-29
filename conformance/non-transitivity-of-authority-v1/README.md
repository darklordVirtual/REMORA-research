# Non-transitivity-of-authority conformance suite v1

## Run it

```
pip install -e .
python conformance/non-transitivity-of-authority-v1/run_conformance.py --adapter remora
```

Thirteen vectors, one line of output each, a fresh `run-record.json`. No
services, no credentials, no configuration.

## What this is

A cross-implementation statement of NTA-1: authorization of one capability does
not authorize any capability reachable through it. The principle, its three
forms (reachability, argument authority, delegation transitivity) and REMORA's
enforcement are described in
[`docs/security/non-transitivity-of-authority.md`](../../docs/security/non-transitivity-of-authority.md).

## What is in here

| file | role |
|---|---|
| `vectors.json` | the fixed world and the 13 vectors. Implementation-agnostic: a step programme and a normalized expected outcome class. |
| `adapter.py` | the adapter contract: `resolve`, `delegate`, `authorize`, `dispatch`, `revoke`. |
| `adapter_skeleton.py` | a runnable adapter with nothing implemented; every vector reports UNSUPPORTED until you fill a method in. |
| `adapter_remora.py` | the REMORA adapter, including the map from REMORA refusal reasons to outcome classes. |
| `run_conformance.py` | the runner. Emits `run-record.json`. |
| `run-record.json` | the current author-run record. |

## What the record binds

The run record names `suite_sha256`, `adapter_sha256`, `runner_sha256` and the
repository commit, hashed over LF-normalized bytes. Vectors are reported one by
one; there is no aggregate score, and UNSUPPORTED is neither a pass nor a
failure.

## What a match does not show

A match shows that the system refuses the vector at its enforcement point. It
does not show that every path to the downstream capability passes through that
point. A wrapper that reaches a capability with a credential of its own is
outside any enforcement point, and no vector here can detect it.
