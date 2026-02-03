from __future__ import annotations

from functools import lru_cache

import requests
from requests.adapters import HTTPAdapter


def _build_adapter() -> HTTPAdapter:
    # Keep pools small for RPi, but reuse connections for better throughput.
    return HTTPAdapter(pool_connections=8, pool_maxsize=8, pool_block=True)


@lru_cache(maxsize=4)
def get_shared_session(name: str = "default") -> requests.Session:
    """Shared requests.Session with connection pooling."""
    sess = requests.Session()
    adapter = _build_adapter()
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    return sess
