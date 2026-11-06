# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reconcile the plant's journal with REMORA's dispatch record (AACP E and G).

Two independent records of the same plant: the plant journals every request
it answered, and REMORA's chain records every dispatch it ran. If the
governed path is the only path to the effect, they agree:

* every write the plant applied names a dispatch REMORA ran, of the same tool
  (``unattributed_writes`` and ``tool_mismatches`` are empty), and no dispatch
  is named by two applied writes (``dispatches_named_twice``);
* every write dispatch REMORA executed has an applied write at the plant
  (``dispatches_without_plant_record``);
* the plant's live state equals the state replayed from its journal
  (``journal_complete``), so no change escaped the journal.

Attribution is computed over the whole history and then reported for the
interval after ``since_seq``. Windowing the journal alone would let a write in
the interval reuse a dispatch reference from before it, and would report the
dispatches made before the interval as missing.

A dispatch REMORA ran with an unknown outcome (``state_unknown``) accounts for
a write that names it: the plant may have applied it, and only the plant can
say. It is never counted as missing, because REMORA does not claim it ran.

An applied write that names no dispatch REMORA ran, or names one of another
tool, did not come through the governed dispatch, whatever credential it used:
that is a bypass, and a run that finds one is a FAIL for E in its scope. The
target of a write is not compared here, because the chain holds no arguments;
the effect receipt binds the arguments to the dispatched call's hash (G).
Standard library only; the plant journal and REMORA's
``GET /v1/execution/dispatches`` are its inputs.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["WRITE_TOOLS", "reconcile"]

WRITE_TOOLS = frozenset({"adjust_setpoint", "set_valve_position", "acknowledge_alarm",
                         "create_work_order", "close_work_order"})

_FIELDS = ("seq", "tool", "arguments", "credential", "dispatch_ref", "source")


def reconcile(journal: Iterable[Mapping[str, Any]],
              dispatches: Iterable[Mapping[str, Any]],
              *, live_digest: str, replayed_digest: str,
              since_seq: int = 0) -> dict[str, Any]:
    """Compare the journal with REMORA's dispatches; report the interval after ``since_seq``."""
    entries = [dict(e) for e in journal]
    rows = [dict(d) for d in dispatches if d.get("tool_name") in WRITE_TOOLS]
    executed = {str(d["proposal_id"]): d for d in rows if d.get("executed")}
    accountable = {str(d["proposal_id"]): d for d in rows
                   if d.get("executed") or d.get("state_unknown")}
    applied = [e for e in entries if e.get("outcome") == "applied"]
    refs = Counter(str(e.get("dispatch_ref") or "") for e in applied)

    def in_window(e: Mapping[str, Any]) -> bool:
        return int(e.get("seq") or 0) > since_seq

    unattributed = [e for e in applied if in_window(e)
                    and str(e.get("dispatch_ref") or "") not in accountable]
    tool_mismatches = [e for e in applied if in_window(e)
                       and str(e.get("dispatch_ref") or "") in accountable
                       and accountable[str(e["dispatch_ref"])].get("tool_name") != e.get("tool")]
    window_refs = {str(e.get("dispatch_ref") or "") for e in applied if in_window(e)}
    duplicated = sorted(ref for ref, n in refs.items() if ref and n > 1 and ref in window_refs)
    missing = sorted(pid for pid in executed if refs.get(pid, 0) == 0)
    window = [e for e in entries if in_window(e)]
    refused = [e for e in window if e.get("outcome") == "refused"]
    return {
        "since_seq": since_seq,
        "journal_entries": len(window),
        "applied_writes": sum(1 for e in applied if in_window(e)),
        "reads": sum(1 for e in window if e.get("outcome") == "read"),
        "refused_requests": len(refused),
        "refused_by_credential": dict(Counter(str(e.get("credential")) for e in refused)),
        "executed_write_dispatches": len(executed),
        "unattributed_writes": [{k: e.get(k) for k in _FIELDS} for e in unattributed],
        "tool_mismatches": [{k: e.get(k) for k in _FIELDS} for e in tool_mismatches],
        "dispatches_named_twice": duplicated,
        "dispatches_without_plant_record": missing,
        "journal_complete": live_digest == replayed_digest,
        "agree": (not unattributed and not tool_mismatches and not duplicated
                  and not missing and live_digest == replayed_digest),
    }
