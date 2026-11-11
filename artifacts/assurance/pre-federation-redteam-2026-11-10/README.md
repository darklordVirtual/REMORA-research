# The pre-Federation red-team count, reproduced and read today

NEGATIVE_RESULTS §76 says 36 of 46 targeted attacks succeeded against `master` at `9a3d321`. No artifact listed the 46 or their outcomes. `result.json` does, from `python scripts/reproduce_pre_federation_redteam.py --out result.json`.

| Run | Probes | Red | Green |
|---|---|---|---|
| Draft PR #744's probe files on a worktree of `9a3d321` | 46 | 36 | 10 |
| The same probe bytes against the working tree | 46 | 8 | 38 |
| `tests/test_pre_federation_*.py` as they are now | 54 | 0 | 54 |

The first row is §76's count, reproduced.

## The eight original probes that still fail

They are not regressions, and each is listed in `result.json` with the first line of its failure.

Five target the v1 Federation packages `effect-evidence-v1` and `exact-call-binding-v1`. §76 says those packages keep their bytes and are marked superseded with their blind spots recorded, so the probes fail there by decision. The repository's probes of the same names read the v1.1 successors.

Three are receipt probes that post a receipt to a chain that records no assessment. Two are refused earlier than they expect, with `assessment_decision_unknown`, so they no longer reach their target; the refusal is still a refusal. The third reaches it: its unbound receipt is refused with `binding_incomplete`, as the probe wants, and its follow-up receipt is then refused with `toolspec_hash_mismatch`, because the probe's chain names no assessed ToolSpec. The repository's probes of the same names build the chain a real dispatch records and pass.

## What it does not show

The 54 probes and their repairs have one author. That is why §76 is open, and this reproduction does not change it. The baseline run uses today's interpreter and dependencies on the old tree; it matched §76's count, which need not hold for a later environment. The probe commit is the head of a closed pull request and is on no branch, so the script fetches `pull/744/head` when the commit is missing.
