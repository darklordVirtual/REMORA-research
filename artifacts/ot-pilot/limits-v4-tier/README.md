# The v4 candidate with the PIC-101 second tier: a read-off on spent data

`limits-candidate-v4-tier.json` is the v4 candidate with one addition. The v4 candidate is `../limits-v4/limits-candidate-v4.json`: valve travel 200 % per hour, and moves of FIC-220 towards its safe value free. The addition is the tier the deployed policy has had since #1196, `dual_control_above` 50 on `pic-101-movement`. Nothing else differs.

It is not deployed and cannot be deployed as it is. It is signed with a key generated for this read-off, whose seed was discarded and whose public key is `limits-candidate-v4-tier.trusted-key`. The pilot trusts the owner's limit authority and the #1196 authority, not this key. Deploying these terms needs a signature from one of those, which is the owner's decision.

## Why

NEGATIVE_RESULTS §97 records that no policy on file has both the v4 changes and the tier. The deployed policy keeps v3's refusals at stops. The v4 candidate removes them and drops the tier, so the independent scenario S20 would run again.

## What is read off, committed before the results

Every file below has been replayed before, so this is a description of data already seen and not a holdout. Nothing is tuned to it: both changes were fixed earlier, on other data. This section was committed (`840e6662`) before the results (`9f32e001`). Git shows that order and nothing more; the read-off tool was written before the first commit. The three expectations also follow from how the tier works, so meeting them confirms the mechanism and is not a discovery.

Legitimate side, with `scripts/run_limits_holdout.py`: the 170 shifts of the development set and holdouts v1 to v4 (`shifts.json`, `shifts-A.json` to `shifts-H.json`), under this policy with one approver per write and with two.

Protective side, with `scripts/run_limits_protection.py --policy-readoff`: the 40 misuse episodes of `../limits-v4/misuse/`, under this policy with one approver and with two, paired with the v4 candidate and with v3.

Expected, and checkable against the result:

- With two approvers every write has the outcome it has under the v4 candidate, on both sides. The tier only asks for a second approver.
- With one approver, harm is reached in no episode in which the v4 candidate does not reach it.
- With one approver, every shift with a refusal under this policy and none under the v4 candidate is refused by the PIC-101 tier and by nothing else.

Any other outcome is recorded as it falls.

## Result

All three expectations held. This policy's and the v4 candidate's rows are from the files in `result/`. The deployed policy's misuse figures, 18 and 17, are from the earlier read-off `../limits-v4/result/protection-deployed-readoff.json`.

| Policy | Approvers per write | Shifts with a limit refusal, of 170 | Misuse episodes that reach their harm, of 40 |
|---|---|---|---|
| deployed (v3 plus tier) | 2 | 13 | 18 |
| deployed (v3 plus tier) | 1 | 46 | 17 |
| v4 candidate | 1 | 2 | 23 |
| v4 candidate plus tier | 2 | 2 | 23 |
| v4 candidate plus tier | 1 | 38 | 22 |

- With two approvers, all 1934 shift writes and all 623 misuse writes have the outcome, reason and refusing limits they have under the v4 candidate, and each misuse episode reaches its harm at the same minute. The two shifts still refused are `hB-18` (alarm acknowledgements) and `hD-03` (the PIC-101 cap of 1.60 bar).
- With one approver, 37 of 170 shifts need a second approver under either tiered policy. The 36 shifts refused under this policy and not under the v4 candidate are all refused by the tier, with reason `limit_dual_control_unmet`. The tier stops one misuse episode, `mB-02`.
- Against the deployed policy with two approvers, these terms remove 11 of 13 shift refusals: 10 valve-travel writes and 2 FIC-220 writes. They give up five misuse episodes that v3 stops, and that the deployed policy with two approvers stops as well by the earlier read-off: `mB-07`, `mW-07`, `mW-09`, `mW-12` and `mW-13`.
- With one approver, which is the replay tool's default, the comparison is 38 against 46 refused shifts and 22 against 17 harms.

The shift files and the episodes were all replayed before, and the policy-aware episodes were written against the v4 candidate's terms. This is a read-off, not a measurement of how either side generalises.

Reproduce the protective side from the repository root with `python scripts/run_limits_protection.py artifacts/ot-pilot/limits-v4/misuse/episodes-B.json artifacts/ot-pilot/limits-v4/misuse/episodes-W.json --policy-readoff artifacts/ot-pilot/limits-v4-tier/limits-candidate-v4-tier.json --trusted-key artifacts/ot-pilot/limits-v4-tier/limits-candidate-v4-tier.trusted-key --out artifacts/ot-pilot/limits-v4-tier/result/protection-readoff.json`. The shift files are replayed with `scripts/run_limits_holdout.py`, `--policy`, `--trusted-key` and `--approvers`.
