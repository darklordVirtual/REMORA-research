# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Print the plant's journal and digests as JSON, from inside the plant container.

For the assessor, who runs it with ``docker compose exec -T plant python
/plant/plant_dump.py``. It reads the plant over loopback with the read token
the container already holds; it adds no credential and no route.
"""
from __future__ import annotations

import json
import os
import urllib.request


def _get(path: str) -> object:
    req = urllib.request.Request(
        f"http://127.0.0.1:{os.environ.get('OT_PLANT_PORT', '9100')}{path}",
        headers={"Authorization": f"Bearer {os.environ['OT_PLANT_READ_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - loopback
        return json.loads(resp.read())


if __name__ == "__main__":
    print(json.dumps({"journal": _get("/journal"), "digest": _get("/digest")}))
