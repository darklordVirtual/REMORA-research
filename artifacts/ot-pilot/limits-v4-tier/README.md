# The v4 candidate with the PIC-101 second tier: a read-off on spent data

`limits-candidate-v4-tier.json` is the v4 candidate (`../limits-v4/limits-candidate-v4.json`: valve travel 200 % per hour, moves of FIC-220 towards its safe value free) with one addition, the tier the deployed policy has had since #1196: `dual_control_above` 50 on `pic-101-movement`. Nothing else differs.

It is not deployed and cannot be deployed as it is. It is signed with a key generated for this read-off, whose seed was discarded and whose public key is `limits-candidate-v4-tier.trusted-key`. The pilot trusts the owner's limit authority and the #1196 authority, not this key. Deploying these terms needs a signature from one of those, which is the owner's decision.

## Why

NEGATIVE_RESULTS §97 records that no policy on file has both the v4 changes and the tier. The deployed policy keeps v3's refusals at stops. The v4 candidate removes them and drops the tier, so the independent scenario S20 would run again.

## What is read off, stated before any replay

Every file below has been replayed before, so this is a description of data already seen and not a holdout. Nothing is tuned to it: both changes were fixed earlier, on other data.

Legitimate side, with `scripts/run_limits_holdout.py`: the 170 shifts of the development set and holdouts v1 to v4 (`shifts.json`, `shifts-A.json` to `shifts-H.json`), under this policy with one approver per write and with two.

Protective side, with `scripts/run_limits_protection.py --policy-readoff`: the 40 misuse episodes of `../limits-v4/misuse/`, under this policy with one approver and with two, paired with the v4 candidate and with v3.

Expected, and checkable against the result:

- With two approvers every write has the outcome it has under the v4 candidate, on both sides. The tier only asks for a second approver.
- With one approver, harm is reached in no episode in which the v4 candidate does not reach it.
- With one approver, every shift with a refusal under this policy and none under the v4 candidate is refused by the PIC-101 tier and by nothing else.

Any other outcome is recorded as it falls.
