# Author: Stian Skogbrott
# License: Apache-2.0
"""Session intent anchoring for governed agent tool calls."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any


def default_session_dir() -> Path:
    """Return the local session-state directory for the current repository."""

    return Path(os.environ.get("REMORA_SESSION_DIR", ".remora_session"))


class IntentAnchor:
    """Persistent intent store for one local agent session.

    The anchor is deliberately local and simple: store the user's declared goal,
    count tool calls, and estimate whether later tool calls drift away from that
    goal. It is a guardrail signal, not semantic proof.
    """

    def __init__(self, session_dir: Path | str | None = None) -> None:
        self.session_dir = Path(session_dir) if session_dir is not None else default_session_dir()
        self.intent_file = self.session_dir / "intent.json"
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.intent_file.exists():
            return
        try:
            self._data = json.loads(self.intent_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def _save(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.intent_file.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    @property
    def anchored(self) -> bool:
        return bool(self._data.get("intent"))

    @property
    def intent(self) -> str:
        return str(self._data.get("intent", ""))

    @property
    def session_id(self) -> str:
        return str(self._data.get("session_id", ""))

    @property
    def tool_call_count(self) -> int:
        return int(self._data.get("tool_call_count", 0))

    def anchor(self, intent: str, session_id: str = "", verified: bool = False) -> None:
        """Store the session intent."""

        self._data = {
            "intent": intent,
            "session_id": session_id,
            "verified": verified,
            "anchored_at": time.time(),
            "tool_call_count": 0,
        }
        self._save()

    def record_tool_call(self) -> int:
        """Increment the tool-call counter and return the new count."""

        count = self.tool_call_count + 1
        self._data["tool_call_count"] = count
        self._save()
        return count

    def drift_score(self, current_action_description: str) -> float:
        """Estimate lexical drift from the anchored intent.

        Returns a score in [0, 1], where 0 means close lexical overlap and 1
        means little overlap. This heuristic is intentionally transparent and
        should be replaced or augmented by embeddings in live deployments.
        """

        if not self.intent:
            return 0.0

        anchor_tokens = _tokens(self.intent)
        action_tokens = _tokens(current_action_description)
        if not anchor_tokens or not action_tokens:
            return 0.0

        overlap = len(anchor_tokens & action_tokens)
        union = len(anchor_tokens | action_tokens)
        jaccard = overlap / union
        substring_bonus = sum(
            1 for token in anchor_tokens if any(token in action for action in action_tokens)
        ) / max(len(anchor_tokens), 1)

        similarity = min(1.0, jaccard + 0.3 * substring_bonus)
        return round(max(0.0, min(1.0, 1.0 - similarity)), 3)

    def clear(self) -> None:
        """Remove the anchored intent."""

        self._data = {}
        if self.intent_file.exists():
            self.intent_file.unlink()


def _tokens(text: str) -> set[str]:
    parts = re.split(r"[\s'\"{}:/\\._,;()[\]-]+", text.lower())
    return {part for part in parts if len(part) > 3}
