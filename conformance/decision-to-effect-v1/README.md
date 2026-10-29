# Decision-to-effect conformance suite v1

## Run it

```
git clone https://github.com/darklordVirtual/REMORA-research
cd REMORA-research
pip install -e .
python conformance/decision-to-effect-v1/run_conformance.py --adapter remora
```

Fifteen vectors, one line of output each, a fresh `run-record.json`. No services,
no credentials, no configuration.

## What this is

A cross-implementation test of the seam between an authorization decision and
the effect that decision authorizes. It exists because "the tool call was
authorized" hides several separable questions, and two systems can only compare
answers if the questions are asked in a form neither of them owns.

## What is in here

| file | role |
|---|---|
| `ONE-PAGE.md` | the one-page trace: the path, five negative cases, the crosswalk in brief. |
| `EXECUTION-TRACE.md` | the evidence note behind it. |
| `vectors.json` | the vectors. Implementation-agnostic: a step programme and a normalized expected outcome class. No REMORA in it. |
| `adapter.py` | the adapter contract. The only interface an implementation must satisfy. |
| `adapter_skeleton.py` | a runnable second adapter with nothing implemented: every vector reports unsupported until you fill a method in. |
| `adapter_remora.py` | the REMORA adapter, including the explicit map from REMORA refusal reasons to outcome classes. |
| `run_conformance.py` | the runner. Emits `run-record.json`. |
| `run-record.json` | the current author-run record. |

## What the record binds

The run record names `suite_sha256`, `adapter_sha256`, `runner_sha256` and the
repository commit. Hashes are taken over LF-normalized bytes, so a Windows and a
Linux checkout of the same file agree; a platform difference must not read as a
conformance difference.

## Writing a second adapter

`adapter_skeleton.py` is a runnable starting point: every method raises
`Unsupported`, so `--adapter skeleton` reports fifteen unsupported vectors and
nothing else. Copy it, fill in the methods your system can express, and each one
you implement turns into a result. Two rules matter more than the code. 

1. **Report what your system decided, never what the vector expects.** If a
   refusal reason has no mapping, report `UNMAPPED:<reason>` and add the mapping
   deliberately. An adapter that decides an outcome on its own branch has tested
   the adapter.
2. **Raise `Unsupported` rather than approximating.** An unsupported vector is a
   legitimate result. It is recorded, and it is neither a pass nor a failure.

The first version of the REMORA adapter got rule 1 wrong on V-11: it checked
revocation in the adapter's own dictionary and passed. It now calls the review
queue and reports the queue's decision. The vector went from proving nothing to
proving something, and the observable result did not change, which is exactly
why this failure mode is worth naming.

## Results

There is no aggregate score, and producing one is a conformance error. Vectors
are reported individually. `run-record.json` carries `run_kind: author-run`;
only a record produced by someone other than the implementer may say otherwise.

Current author-run against REMORA: 15 of 15 match under the suite's own
conditions, on vectors written by the same author as the implementation. The
record is marked `author-run` for that reason. An independent run is the only
kind that carries weight, and REMORA's capability register claims neither
`ENFORCED_PRODUCTION` nor `EXTERNALLY_VERIFIED`.

## Known limits

- The suite drives one process. V-05 demonstrates single-use consumption under
  eight concurrent threads, which is process-local evidence. Multiprocess and
  restart behaviour depend on a durable ledger being configured and are not
  claimed here.
- V-06 presents a future clock to the dispatcher rather than moving the system
  clock.
- V-12 issues the authority for a different runtime and presents it here, which
  is the same refusal path as executing an authority on the wrong runtime but is
  not a second machine.
- Effect verification uses an in-suite reader. A system of record would be the
  stronger evidence producer, and the suite is built so that swapping it in
  changes the adapter and not the vectors.

## Public GitHub Actions self-test badge (external projects)

An external project can test **its own implementation** against these vectors.
This is a self-run workflow, not a REMORA certification or independently
verified result. It requires a single-file Python adapter that invokes the
actual system under test and implements the methods in `adapter_skeleton.py`.
Never derive an outcome from a vector's expected answer. Run against a
non-production test target; the suite includes synthetic `transfer_funds` calls.

1. Copy `adapter_skeleton.py` into the external repository, for example as
   `remora_adapter.py`. Implement it against that repository's real code;
   return `Unsupported` for missing mechanisms.
2. After the reusable workflow has merged, replace both `FULL_REMORA_COMMIT_SHA`
   placeholders below with the **same 40-character SHA** of the REMORA revision
   containing the workflow and suite. Create the file
   `.github/workflows/remora-selftest.yml` in the external repository:

   ```yaml
   name: REMORA D2E self-test
   on: [push, pull_request, workflow_dispatch]
   permissions:
     contents: read
   jobs:
     vectors:
       uses: darklordVirtual/REMORA-research/.github/workflows/remora-d2e-selftest-reusable.yml@FULL_REMORA_COMMIT_SHA
       with:
         suite_sha: FULL_REMORA_COMMIT_SHA
         adapter_file: remora_adapter.py
   ```

3. Put a **GitHub workflow status** badge into the external project's README,
   replacing `OWNER/REPO` and `main` with its own repository/default branch:

   ```markdown
   [![REMORA D2E self-test (self-reported)](https://github.com/OWNER/REPO/actions/workflows/remora-selftest.yml/badge.svg?branch=main)](https://github.com/OWNER/REPO/actions/workflows/remora-selftest.yml)
   ```

The caller's badge goes green only if every pinned vector reports `MATCH`.
The dedicated `scripts/check_external_conformance.py` gate also checks the
suite/runner/adapter digests, exact case identities and counts, and the suite
commit. Any divergent, unsupported, missing or crashed vector makes the
workflow red. The original runner still exits zero to retain its full
per-vector report; the badge gate adds the stricter CI outcome.

GitHub stores the raw `conformance-run.json` as a workflow artifact even
on a red run. This report uses the current runner's conservative
`run_kind: author-run` value; it does not assert independent operation.
The workflow runs caller-controlled adapter code with read-only permissions
and no inherited secrets. It does not grant production-use rights beyond
[the REMORA license](../../LICENSE).

**Trust boundary:** A repository owner can write an adapter that only returns
the expected labels. A green self-test therefore proves neither real
runtime enforcement nor a complete interception surface. For a separate
independent-verification claim, require externally operated tests,
independently validated inputs and provenance under the
[Federation result rules](../../docs/interop/FEDERATION.md).
Do not call this self-test badge 'Certified', 'Audited' or 'Verified'.
