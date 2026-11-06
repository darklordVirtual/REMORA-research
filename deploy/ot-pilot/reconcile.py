# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reconcile the plant's journal with REMORA's dispatch record (AACP E and G).

Two independent records of the same interval: the plant journals every
request that reached it, and REMORA's chain records every dispatch it
executed. If the governed path is the only path to the effect, they agree:

* every write the plant applied names a dispatch REMORA executed
  (``unattributed_writes`` is empty), and no dispatch is named twice;
* every write dispatch REMORA executed has exactly one applied write at the
  plant (``dispatches_without_plant_record`` is empty);
* the plant's live state equals the state replayed from its journal
  (``journal_complete``), so no change escaped the journal.

An applied write whose ``dispatch_ref`` names no executed dispatch is a write
that did not come through REMORA's governed dispatch, whatever credential it
used: that is a bypass, and a run that finds one is a FAIL for E in its
scope. Standard library only; the plant journal and REMORA's
``GET /v1/execution/dispatches`` are its inputs.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["WRITE_TOOLS", "reconcile"]

WRITE_TOOLS = frozenset({"adjust_setpoint", "set_valve_position", "acknowledge_alarm",
                         "create_work_order", "close_work_order"})


def reconcile(journal: Iterable[Mapping[str, Any]],
              dispatches: Iterable[Mapping[str, Any]],
              *, live_digest: str, replayed_digest: str,
              since_seq: int = 0) -> dict[str, Any]:
    """Compare one interval of the journal with REMORA's executed dispatches.

    ``since_seq`` restricts the journal to entries after that sequence number,
    for a run that starts on a plant with earlier history.
    """
    entries = [dict(e) for e in journal if int(e.get("seq") or 0) > since_seq]
    applied = [e for e in entries if e.get("outcome") == "applied"]
    executed = {str(d["proposal_id"]): dict(d) for d in dispatches
                if d.get("executed") and d.get("tool_name") in WRITE_TOOLS}
    refs = Counter(str(e.get("dispatch_ref") or "") for e in applied)
    unattributed = [e for e in applied
                    if str(e.get("dispatch_ref") or "") not in executed]
    duplicated = sorted(ref for ref, n in refs.items() if ref and n > 1)
    missing = sorted(pid for pid in executed if refs.get(pid, 0) == 0)
    refused = [e for e in entries if e.get("outcome") == "refused"]
    return {
        "journal_entries": len(entries),
        "applied_writes": len(applied),
        "refused_requests": len(refused),
        "refused_by_credential": dict(Counter(str(e.get("credential")) for e in refused)),
        "executed_write_dispatches": len(executed),
        "unattributed_writes": [
            {k: e.get(k) for k in ("seq", "tool", "arguments", "credential",
                                   "dispatch_ref", "source")}
            for e in unattributed],
        "dispatches_named_twice": duplicated,
        "dispatches_without_plant_record": missing,
        "journal_complete": live_digest == replayed_digest,
        "agree": (not unattributed and not duplicated and not missing
                  and live_digest == replayed_digest),
    }
