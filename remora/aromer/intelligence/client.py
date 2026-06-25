from __future__ import annotations
import os
import urllib.request
import urllib.error
import json
from typing import Optional, List

from .score import IntelligenceScore

AROMER_BASE_URL = os.environ.get(
    "AROMER_WORKER_URL", "https://aromer.razorsharp.workers.dev"
)

_DEFAULT_HEADERS = {
    "User-Agent": "REMORA-IntelligenceClient/1.0",
    "Accept": "application/json",
}


def _get(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AROMER /intelligence unreachable: {exc}") from exc


class IntelligenceClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self._base = (base_url or AROMER_BASE_URL).rstrip("/")

    def current(self, history_hours: int = 1) -> IntelligenceScore:
        url = f"{self._base}/intelligence?history={history_hours}"
        data = _get(url)
        return IntelligenceScore.from_api(data)

    def history(self, hours: int = 24) -> List[dict]:
        url = f"{self._base}/intelligence?history={hours}"
        data = _get(url)
        return data.get("history", [])
