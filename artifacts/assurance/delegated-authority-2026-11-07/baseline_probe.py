# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The four delegation questions against the A2A envelope as it was at dea40402.

Run at that commit: git checkout dea40402 && python <this file>. It writes the
failures each verify() returned, or "VALID", to stdout (baseline.json here).
At a later commit the strict verifier also asks for expected_roots, so the
numbers are only this commit's.
"""
import json
import sys
from datetime import UTC, datetime
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3]))
from remora.governance.a2a_envelope import (A2AGovernanceEnvelope, AgentIdentity, DelegationLink,
    RegisteredKey, sign_delegation_link)
from remora.policy.observation import canonical_tool_call_hash
from remora.governance.task_identity import TaskIdentity

NOW = datetime.now(UTC); ISO = NOW.isoformat()
ENV_KEY = b"shared-envelope-key-32-bytes-long!!"
K = {"origin": b"origin-key-0000000000000000000000", "mid": b"mid-key-00000000000000000000000000",
     "shared": b"one-key-every-agent-holds-000000000"}
def link(d, e, scope, key, kid): return sign_delegation_link(DelegationLink(d, e, tuple(scope), ISO), key=key, kid=kid)
def ident(a): return AgentIdentity(a, "1", "org", "org")
def env(chain, scope, args, agent="worker", task=None):
    h = canonical_tool_call_hash(name="release_payment", arguments=args, target="prod")
    return A2AGovernanceEnvelope.issue(identity=ident(agent), delegation_chain=tuple(chain),
        requested_scope=tuple(scope), policy_version="p1", audience="verifier-1",
        tool_call_hash=h, signing_key=ENV_KEY, task_identity=task), h
seen=set()
def guard(n):
    if n in seen: return True
    seen.add(n); return False
REG = {"k-origin": RegisteredKey(K["origin"], "origin"), "k-mid": RegisteredKey(K["mid"], "mid")}
def v(e, h, reg=REG, g=None, **kw):
    return e.verify(signing_key=ENV_KEY, now=NOW, expected_audience="verifier-1", expected_tool_call_hash=h,
                    link_keys=reg, replay_guard=g or (lambda n: False), **kw)
out={}
# S1 widening at intermediary
e,h = env([link("origin","mid",["payment:release"],K["origin"],"k-origin"), link("mid","worker",["payment:release","vendor:add"],K["mid"],"k-mid")], ["payment:release"], {"amount":250})
out["S1_scope_widened"] = v(e,h).failures
# S2 intermediary changes amount 250 -> 25000 (origin authorized 250 out of band; nothing in the chain carries it)
e,h = env([link("origin","mid",["payment:release"],K["origin"],"k-origin"), link("mid","worker",["payment:release"],K["mid"],"k-mid")], ["payment:release"], {"amount":25000})
out["S2_amount_altered"] = v(e,h).failures or "VALID"
# S2b intermediary re-roots the chain at itself
e,h = env([link("mid","worker",["payment:release","vendor:add"],K["mid"],"k-mid")], ["vendor:add"], {"amount":25000})
out["S2b_rerooted_at_intermediary"] = v(e,h).failures or "VALID"
# S2c one shared key registered for every principal: intermediary signs as origin
SH = {"k-o": RegisteredKey(K["shared"],"origin"), "k-m": RegisteredKey(K["shared"],"mid")}
e,h = env([link("origin","mid",["payment:release","vendor:add"],K["shared"],"k-o"), link("mid","worker",["vendor:add"],K["shared"],"k-m")], ["vendor:add"], {"amount":25000})
out["S2c_shared_key_forged_origin"] = v(e,h,reg=SH).failures or "VALID"
# S3 replay
e,h = env([link("origin","worker",["payment:release"],K["origin"],"k-origin")], ["payment:release"], {"amount":250})
out["S3_first"] = v(e,h,g=guard).failures or "VALID"
out["S3_replay_same_guard"] = v(e,h,g=guard).failures or "VALID"
seen.clear()  # process restart with an in-memory guard
out["S3_replay_after_restart_in_memory_guard"] = v(e,h,g=guard).failures or "VALID"
out["S3_other_audience"] = e.verify(signing_key=ENV_KEY, now=NOW, expected_audience="verifier-2", expected_tool_call_hash=h, link_keys=REG, replay_guard=lambda n: False).failures
# S4 correctly signed chain, other task
t_orig = TaskIdentity(context_id="ctx-1", task_id="invoice-250"); t_other = TaskIdentity(context_id="ctx-1", task_id="add-vendor")
e,h = env([link("origin","worker",["payment:release"],K["origin"],"k-origin")], ["payment:release"], {"amount":250}, task=t_other)
out["S4_other_task_verifier_checks"] = v(e,h,expected_task_identity=t_orig).failures
out["S4_other_task_verifier_does_not_check"] = v(e,h).failures or "VALID"
print(json.dumps(out, indent=1, default=list))
