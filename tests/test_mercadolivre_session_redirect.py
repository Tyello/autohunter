"""ML: shell 200 com a busca vazia traz o redirect canonico (SEO_CANONICAL) no payload
streaming; sessao logada (storage_state) evita o gate account-verification."""

from app.scrapers import mercadolivre as ml

SHELL_TAIL = (
    '<script nonce="x">_n.ctx.s["nr"].q("0:{\\"redirect\\":{\\"isRedirect\\":true,\\"status\\":301,'
    '\\"headers\\":{\\"x-redirect-cause\\":\\"SEO_CANONICAL\\",\\"Cache-Control\\":\\"public,max-age=3600\\",'
    '\\"siteIsoCode\\":\\"BR\\",\\"Location\\":\\"https:\\u002F\\u002Flista.mercadolivre.com.br\\u002F'
    'veiculos\\u002Fcarros-caminhonetes\\u002Fhonda\\u002Fcivic\\u002F\\"}}}\\n");</script>'
)


def test_extract_nordic_redirect_returns_canonical_url():
    html = "<html>" + ("x" * 100) + SHELL_TAIL + "</html>"
    assert ml._extract_nordic_redirect(html) == (
        "https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/honda/civic/"
    )


def test_extract_nordic_redirect_none_without_redirect():
    assert ml._extract_nordic_redirect("<html>sem redirect</html>") is None
    assert ml._extract_nordic_redirect("") is None


def test_session_cookies_only_mercadolivre_domains(monkeypatch):
    fake = [
        {"name": "ssid", "value": "a", "domain": ".mercadolivre.com.br"},
        {"name": "x", "value": "b", "domain": ".google.com"},
        {"name": "empty", "value": None, "domain": ".mercadolivre.com.br"},
    ]
    import app.scrapers.hybrid_cookies as hc

    monkeypatch.setattr(hc, "_load_storage_state_cookies", lambda **k: fake)
    assert ml._ml_session_cookies(None) == {"ssid": "a"}


def test_polycard_sample_is_dumped_once_per_interval(monkeypatch, tmp_path):
    from app.scrapers import mercadolivre as ml

    monkeypatch.setattr(ml, "health_dir", lambda: tmp_path)
    html = '<script>{"polycard":{"metadata":{"id":"MLB1"},"components":[{"type":"attributes_list"}]}}</script>' * 3
    ml._dump_polycard_sample(html, "https://lista.mercadolivre.com.br/x")
    out = (tmp_path / "ml_polycard_sample.txt").read_text(encoding="utf-8")
    assert "attributes_list" in out and out.count("=====") == 2  # cabecalho + 2 amostras

    (tmp_path / "ml_polycard_sample.txt").write_text("keep", encoding="utf-8")
    ml._dump_polycard_sample(html, "https://lista.mercadolivre.com.br/x")  # dentro de 1h: nao sobrescreve
    assert (tmp_path / "ml_polycard_sample.txt").read_text(encoding="utf-8") == "keep"
