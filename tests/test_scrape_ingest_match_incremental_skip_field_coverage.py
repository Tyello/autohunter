"""Regressao: quando o modo incremental (source_configs.extra.incremental_enabled)
detecta que o anuncio "top" nao mudou desde a ultima run, scrape_ingest_match /
scrape_ingest_match_many pulam o trabalho de banco (otimizacao legitima -- se nada
mudou, re-notificar seria redundante) mas o dict retornado nesse atalho nao incluia
`field_coverage`, mesmo ele ja tendo sido calculado a partir do fetch real logo
acima (compute_field_coverage(listings_all)).

Isso fazia o agregado em source_execution_service.total_field_present (e o alerta
em operational_alerts_service._field_coverage_alerts) ficarem sistematicamente
zerados para qualquer source com baixo turnover de inventario que passa a maior
parte do tempo no atalho -- turboclass, por exemplo, tinha found=27 reais (com
price/year corretos) todo run, mas o skip apagava esse sinal, dando a falsa
impressao de que o parser tinha quebrado (ver commit que corrige isto)."""

from __future__ import annotations

from decimal import Decimal

from app.scheduler.jobs import scrape_ingest_match
from app.services.source_url_cursors_service import touch_cursor
from app.sources.types import ScrapeContext


def _listings():
    return [
        {
            "source": "turboclass",
            "external_id": "tc-top",
            "url": "https://turboclass.com.br/anuncio/detalhe/tc-top",
            "title": "Honda Civic SI Turbo 2007",
            "price": Decimal("165900.00"),
            "year": 2007,
            "thumbnail_url": "https://turboclass.com.br/img/tc-top.jpg",
        },
        {
            "source": "turboclass",
            "external_id": "tc-second",
            "url": "https://turboclass.com.br/anuncio/detalhe/tc-second",
            "title": "Honda Civic SI Aspirado 2007",
            "price": Decimal("95000.00"),
            "year": 2007,
            "thumbnail_url": "https://turboclass.com.br/img/tc-second.jpg",
        },
    ]


def test_incremental_skip_still_reports_field_coverage(db, monkeypatch):
    # system_logs.tags is a postgres ARRAY(Text); the sqlite test DB has no bind
    # processor for it (unrelated pre-existing gap), so no-op the logging calls --
    # this test only cares about scrape_ingest_match's return value.
    monkeypatch.setattr("app.scheduler.jobs.log", lambda *a, **kw: None)
    monkeypatch.setattr("app.scheduler.jobs.emit_event", lambda *a, **kw: None)

    url = "https://turboclass.com.br/anuncio-lista.php?q=civic+si"
    ctx = ScrapeContext(source="turboclass", extra={"incremental_enabled": True})

    # Seed the cursor so the very first call already sees "top unchanged"
    # (this is exactly the steady state a low-turnover source sits in for days).
    touch_cursor(db, source="turboclass", url=url, last_external_id="tc-top")
    db.commit()

    res = scrape_ingest_match(
        db,
        "scraper_turboclass",
        lambda u, ctx: _listings(),
        url,
        ctx=ctx,
    )

    assert res["ok"] is True
    assert res["incremental"] == "skip"
    assert res["found"] == 2

    fc = res.get("field_coverage")
    assert fc is not None, "field_coverage foi omitido no retorno do modo skip"
    assert fc["price"]["present"] == 2
    assert fc["year"]["present"] == 2
    assert fc["price"]["rate"] == 1.0
