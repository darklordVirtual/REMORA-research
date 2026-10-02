# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import io
import urllib.request

import pytest

from remora.evidence.worker_client import REMORAWorkerClient


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_read_timeout_becomes_connection_error(monkeypatch) -> None:
    class _Slow:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Slow())
    with pytest.raises(ConnectionError):
        REMORAWorkerClient("https://example.invalid")._post("/x", {})


def test_invalid_json_becomes_connection_error(monkeypatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(b"<html>"))
    with pytest.raises(ConnectionError):
        REMORAWorkerClient("https://example.invalid")._post("/x", {})
