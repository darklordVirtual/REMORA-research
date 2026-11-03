# SPDX-License-Identifier: BUSL-1.1
"""Shared model responses across paired arms (common random numbers).

**Design, to be stated in the SAP.** Every arm of the control evaluation
runs the same episode: the same user task, the same injection, the same
untrusted agent. Arms differ only in which proposed tool calls they let run.
Up to the first call where two arms' defences decide differently, their
trajectories are identical, so the agent's request to the model is
byte-for-byte the same in both. This module gives such identical requests
one shared sample instead of one sample per arm.

The rule: the *k*-th time an arm sends request *R* within episode *P*, it
receives the *k*-th response ever obtained for (*P*, *R*), sampling a new one
only when fewer than *k* exist. *R* is the canonical JSON of the request
(model, system, tools, messages, and every other request field), hashed with
SHA-256. *P* is the episode key: suite, user task, injection task (or none
for a benign run) and the run id. Counting occurrences keeps AgentDojo's
own retry (it reruns a task whose final output is empty) a fresh sample
rather than a replay.

What this changes, and what it does not:

* Each arm's trajectory has the same marginal distribution as without
  sharing: every response is a draw from the model for exactly that request.
* Arms become positively coupled within an episode. Paired comparisons
  (McNemar, the cluster sign-flip test in ``metrics``) are the right
  analysis for coupled arms and gain power from it. An analysis that treats
  arms as independent samples would be wrong.
* Arms whose defences agree on every call (for example A and C on a task
  whose calls are all allowlisted) produce the same trajectory. That is the
  point of the design, not a defect.
* The current models reject ``temperature``, so the agent samples at the
  provider's default. Without sharing, arm differences would mix defence
  effects with sampling noise from the first turn on.

The cache is stored on disk as append-only JSONL under the run id, so a
resumed run replays what it already paid for instead of sampling again.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def canonical_request(request: Mapping[str, Any]) -> str:
    """Canonical JSON of a Messages API request: sorted keys, no whitespace."""
    return json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=str)


def request_hash(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_request(request).encode("utf-8")).hexdigest()


class ResponseCache:
    """Disk-backed CRN cache for one run.

    ``lookup`` and ``store`` take the episode key, the arm and the request.
    The occurrence index is tracked per (episode, arm, request) in memory, so
    a new process replays each arm from occurrence 0 against what is on disk.
    """

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self._samples: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self._seen: dict[tuple[str, str, str], int] = defaultdict(int)
        self.hits = 0
        self.misses = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("run_id") != run_id:
                    raise ValueError(f"{self.path} belongs to run {row.get('run_id')!r}, "
                                     f"not {run_id!r}")
                self._samples[(row["episode"], row["request"])].append(row["response"])

    def _next(self, episode: str, arm: str, request: Mapping[str, Any]) -> tuple[str, int]:
        h = request_hash(request)
        k = self._seen[(episode, arm, h)]
        self._seen[(episode, arm, h)] = k + 1
        return h, k

    def lookup(self, episode: str, arm: str, request: Mapping[str, Any]
               ) -> tuple[dict[str, Any] | None, str, int]:
        """Return (shared response or None, request hash, occurrence index)."""
        h, k = self._next(episode, arm, request)
        samples = self._samples.get((episode, h), [])
        if k < len(samples):
            self.hits += 1
            return samples[k], h, k
        self.misses += 1
        return None, h, k

    def store(self, episode: str, request_sha: str, occurrence: int,
              response: Mapping[str, Any]) -> None:
        samples = self._samples[(episode, request_sha)]
        if occurrence != len(samples):
            raise RuntimeError("cache store out of order; occurrences must be filled in sequence")
        row = {"run_id": self.run_id, "episode": episode, "request": request_sha,
               "occurrence": occurrence, "response": dict(response)}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        samples.append(dict(response))
