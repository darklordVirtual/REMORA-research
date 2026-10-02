# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The recorder must bound a request line before buffering all of it."""
from __future__ import annotations

import io

from remora.audit import recorder as module


class _Counting(io.RawIOBase):
    def __init__(self, total):
        self.left = total
        self.served = 0

    def readable(self):
        return True

    def readinto(self, b):
        n = min(len(b), self.left)
        b[:n] = b"x" * n
        self.left -= n
        self.served += n
        return n


def test_overlong_line_is_not_fully_buffered():
    total = module._MAX_LINE * 8
    src = _Counting(total)
    rfile = io.BufferedReader(src, buffer_size=8192)
    written = io.BytesIO()
    handler = module._Handler.__new__(module._Handler)
    handler.rfile = rfile
    handler.wfile = written
    handler.server = type("S", (), {"store": None})()
    handler.handle()
    assert b"too large" in written.getvalue()
    assert src.served < total, "over-long line was buffered in full"
    assert src.served <= module._MAX_LINE + 2 * 8192
