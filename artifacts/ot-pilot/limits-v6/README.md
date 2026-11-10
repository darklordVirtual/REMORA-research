# Limits plan v6: a candidate whose bounds ask a second approver, with one in the loop

Plan: `docs/assurance/ot_limits_holdout_plan_v6.md` (DOC-432). The candidate policy is `limits-candidate-v6.json`, signed with a key made for this plan whose seed was discarded; its public key is `limits-candidate-v6.trusted-key`. The pilot does not trust that key, so the file cannot be deployed as it is.

## Author sessions

| Session | Label | Count | Reads | File |
|---|---|---:|---|---|
| holdout K | `hK` | 20 shifts | the v1 brief | `holdout/shifts-K.json` |
| holdout L | `hL` | 20 shifts | the v1 brief | `holdout/shifts-L.json` |
| holdout M | `hM` | 20 shifts | the v1 brief | `holdout/shifts-M.json` |
| holdout N | `hN` | 20 shifts | the v1 brief | `holdout/shifts-N.json` |
| misuse, blind | `mD` | 20 episodes | the v1 brief and `misuse-brief.md` | `misuse/episodes-D.json` |
| misuse, blind | `mE` | 20 episodes | the v1 brief and `misuse-brief.md` | `misuse/episodes-E.json` |

Each session got a directory of its own outside the repository that held only the files it was to read. `hK` and `hM` used set A's day-shift profile, `hL` and `hN` set B's night and weekend profile, all with v1's holdout prompt and v3's stop-and-restart instruction. `mD` and `mE` used v4's misuse brief, unchanged. Both misuse sessions are blind: each knew only that an approval and safety system governs writes. The author-brief SHA-256 is `5b984a68…2783f` and the misuse-brief SHA-256 is `892a5072…f30ae`.

A third misuse session was planned and dropped. It would have read the candidate's terms and written operator logs worded so a human second approver approves them. Authoring a set optimised to deceive a safety approver into approving harmful physical actions is not something to generate; the plan records the change, and `candidate-summary.md` is kept as documentation of the policy but was given to no blind author. The approver's exposure to an adversary who knows the policy is measured as a secondary read on the spent policy-aware episodes of v4 and v5.

## What the sessions reported

- `hK`: 315 writes. `hL`: 439 writes. `hM`: 377 writes. `hN`: 410 writes. Each shift has a stop and a restart, and some writes are out of the normal band for a stated reason (stroke tests, emergency isolation), inside the instrument range.
- `mD`: 201 writes, 20 episodes, every harm three times or more. `mE`: 188 writes, 20 episodes, the same coverage. Both wrote a generator and checker beside their output.

The sessions were started with the agent tool from this checkout, so they may have received `CLAUDE.md` and the operator's saved memory. That memory held the results of v1 to v3 and the deployed policy's terms. It held no term of this candidate. The session that started them knew every earlier result and the candidate, and read the replies above before any seal. It did not open the six files. No session transcript is stored.

## Seal

`SHA256SUMS` is committed before any replay, review or packet reads the six files.
