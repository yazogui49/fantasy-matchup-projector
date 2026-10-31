from __future__ import annotations

import hashlib
import json
import time

import requests

from .config import CACHE_DIR


def get_json(url: str, ttl: float | None = 3600) -> dict:
    """GET a JSON URL, reusing a cached copy younger than `ttl` seconds.
    ttl=None means the cached copy never expires (for data that can't change)."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if path.exists() and (ttl is None or time.time() - path.stat().st_mtime < ttl):
        return json.loads(path.read_text())

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    path.write_text(json.dumps(data))
    return data
