"""Regressao: o storage_state do Playwright guarda `cf_clearance` (e __cf_bm/_cfuvid),
que o Cloudflare amarra ao fingerprint do browser headless. Reenviado junto com o TLS
do curl_cffi, vira 403 no OLX -- e o fallback p/ browser regrava o cookie, mantendo o
ciclo (prod 09/10: 69 bloqueios seguidos; sem o cookie o mesmo request dava 200).

_load_playwright_cookies_for_olx deve devolver so cookies de sessao do OLX, sem os
cookies de challenge do Cloudflare."""

import json
from types import SimpleNamespace

from app.scrapers import olx as olx_mod


def _write_state(tmp_path, monkeypatch, cookies):
    monkeypatch.setattr(olx_mod, "playwright_storage_dir", lambda: tmp_path)
    ctx = SimpleNamespace(source="olx", proxy_server=None)
    path = olx_mod._storage_state_path_for_ctx(ctx, "olx")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies}, f)
    return ctx


def test_cloudflare_challenge_cookies_are_not_replayed(tmp_path, monkeypatch):
    ctx = _write_state(
        tmp_path,
        monkeypatch,
        [
            {"name": "cf_clearance", "value": "a", "domain": ".olx.com.br"},
            {"name": "__cf_bm", "value": "b", "domain": ".olx.com.br"},
            {"name": "_cfuvid", "value": "c", "domain": ".olx.com.br"},
            {"name": "nl_id", "value": "keep1", "domain": ".olx.com.br"},
            {"name": "r_id", "value": "keep2", "domain": "www.olx.com.br"},
        ],
    )
    assert olx_mod._load_playwright_cookies_for_olx(ctx) == {"nl_id": "keep1", "r_id": "keep2"}


def test_non_olx_domains_still_filtered(tmp_path, monkeypatch):
    ctx = _write_state(tmp_path, monkeypatch, [{"name": "x", "value": "1", "domain": ".other.com"}])
    assert olx_mod._load_playwright_cookies_for_olx(ctx) == {}
