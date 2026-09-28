"""Fase 1B (docs/prompts/PROMPT-exec-melhorias-sources-v2.md): Mercado Livre
vira `deprioritized`, igual Webmotors. Decisao de 28/09: a busca do ML exige
login/verificacao mesmo para visitante anonimo (confirmado com o fixture real
capturado na Fase 0 -- cookies de producao de 9 dias, ainda bloqueado).

Esta suite confirma, com a fixture REAL da Fase 0 (nao HTML sintetico), que:
1. `_is_ml_security_or_captcha_page` classifica a pagina como bloqueio.
2. `scrape_mercadolivre` levanta `FetchBlocked` para essa pagina (nao devolve
   `found=0` silenciosamente -- ver app/scrapers/base.py:FetchBlocked e
   `decide_parse_failure`/`parse_failure.py`, que so cobrem found==0, nao
   bloqueio explicito).
3. Um bloqueio do ML nao conta pra saude critica global, uma vez que
   `operational_role="deprioritized"` esta setado no plugin
   (app/services/source_operational_policy.py: `CRITICAL_ROLES = {"primary",
   "fragile"}`, `deprioritized` cai em `source_operational_severity` como
   "info", nao "critical", e `should_include_in_critical_stale` retorna
   False)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.scrapers.base import FetchBlocked
from app.scrapers.mercadolivre import _is_ml_security_or_captcha_page, scrape_mercadolivre
from app.services.source_operational_policy import (
    classify_source_operational_role,
    should_include_in_critical_stale,
    source_operational_severity,
)
from app.sources.builtins import register_source  # noqa: F401 (garante builtins carregado)
from app.sources.registry import get_source
from app.sources.types import ScrapeContext

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "source_regression"
    / "mercadolivre"
    / "2026-09-28_civic"
    / "listing_shell_com_cookies_bloqueado.html"
)


def _fixture_html() -> str:
    if not FIXTURE.exists():
        pytest.skip(f"fixture ausente: {FIXTURE}")
    return FIXTURE.read_text(encoding="utf-8")


def test_real_blocked_fixture_is_classified_as_security_page():
    html = _fixture_html()
    assert _is_ml_security_or_captcha_page(html) is True


def test_scrape_mercadolivre_raises_fetchblocked_for_real_fixture_not_found_zero(monkeypatch):
    html = _fixture_html()

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", lambda url, ctx=None, timeout=25: html)

    # browser_fallback_enabled=False -> caminho de fallback (browser) nao roda,
    # o bloqueio detectado no HTTP puro ja deve estourar FetchBlocked.
    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=False)
    with pytest.raises(FetchBlocked) as excinfo:
        scrape_mercadolivre(
            "https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/honda-civic", ctx
        )
    assert excinfo.value.reason == "ml_security_or_captcha_page"


def test_mercadolivre_plugin_is_deprioritized_and_disabled_by_default():
    plugin = get_source("mercadolivre")
    assert plugin is not None
    extra = plugin.default_extra or {}
    assert extra.get("operational_role") == "deprioritized"
    assert plugin.default_enabled is False


class _FakeEnabledCfg:
    """`source_configs` real de producao hoje ainda tem is_enabled=True pra
    mercadolivre (o default_enabled=False do plugin so vale pra seed de linha
    nova -- app/services/source_configs_service.py:ensure_source_configs -- a
    linha existente so muda com `/admin sources disable mercadolivre`, nao
    executado por este prompt). Simula esse estado real: cfg.is_enabled=True,
    operational_role="deprioritized" ja lido do plugin."""

    is_enabled = True


def test_deprioritized_mercadolivre_does_not_count_as_critical_health():
    plugin = get_source("mercadolivre")
    assert plugin is not None

    # Estado real de producao hoje (linha existente, ainda nao desabilitada
    # manualmente): cfg.is_enabled=True, role vem do default_extra do plugin.
    classification = classify_source_operational_role(plugin, cfg=_FakeEnabledCfg())
    assert classification.role == "deprioritized"
    assert classification.include_in_critical_stale is False
    assert should_include_in_critical_stale(plugin, cfg=_FakeEnabledCfg()) is False
    assert source_operational_severity(classification.role, enabled=True) == "info"

    # Estado pos-seed-fresco (cfg=None, ex.: banco novo): default_enabled=False
    # faz a fonte nascer ja "disabled" -- tambem nao conta pra saude critica.
    fresh_classification = classify_source_operational_role(plugin, cfg=None)
    assert fresh_classification.role == "disabled"
    assert fresh_classification.include_in_critical_stale is False
