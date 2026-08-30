"""Auditoria empírica read-only para o design de "Buscar agora" (docs/DESIGN_BUSCAR_AGORA.md).

Roda apenas SELECTs contra car_listings (via DATABASE_URL do ambiente) e, opcionalmente,
faz um GET/HEAD real (não Playwright) contra uma amostra de URLs por marketplace para
observar o comportamento hoje de anúncios possivelmente encerrados.

Este script NUNCA escreve no banco e NUNCA faz DDL. É uma ferramenta de diagnóstico de
uma vez só — não é importado por nenhum outro módulo do projeto.

Uso:
    .venv/Scripts/python.exe scripts/audit_buscar_agora_facets.py
    .venv/Scripts/python.exe scripts/audit_buscar_agora_facets.py --sample-size 10
    .venv/Scripts/python.exe scripts/audit_buscar_agora_facets.py --skip-http
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

sys.path.insert(0, ".")

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402

FACET_FIELDS = ["year", "state", "city", "price", "mileage_km", "color", "make", "model"]

NULL_RATE_SQL = text(
    """
    SELECT
        count(*) AS total,
        count(*) FILTER (WHERE year IS NULL) AS year_null,
        count(*) FILTER (WHERE state IS NULL) AS state_null,
        count(*) FILTER (WHERE city IS NULL) AS city_null,
        count(*) FILTER (WHERE price IS NULL) AS price_null,
        count(*) FILTER (WHERE mileage_km IS NULL) AS mileage_km_null,
        count(*) FILTER (WHERE color IS NULL) AS color_null,
        count(*) FILTER (WHERE make IS NULL) AS make_null,
        count(*) FILTER (WHERE model IS NULL) AS model_null
    FROM car_listings
    """
)

OUT_OF_RANGE_SQL = text(
    """
    SELECT
        count(*) FILTER (WHERE year IS NOT NULL AND (year < 1900 OR year > 2100)) AS year_out_of_range,
        count(*) FILTER (WHERE mileage_km IS NOT NULL AND (mileage_km < 0 OR mileage_km > 1500000)) AS mileage_out_of_range,
        count(*) FILTER (WHERE price IS NOT NULL AND price <= 0) AS price_non_positive
    FROM car_listings
    """
)

STATE_DISTINCT_SQL = text(
    """
    SELECT state, count(*) AS n
    FROM car_listings
    WHERE state IS NOT NULL
    GROUP BY state
    ORDER BY n DESC
    LIMIT 40
    """
)

SAMPLE_URLS_SQL = text(
    """
    SELECT source, url
    FROM car_listings
    WHERE source = :source
    ORDER BY random()
    LIMIT :n
    """
)

SOURCES_TO_CHECK = ["mercadolivre", "olx", "chavesnamao"]


@dataclass
class HttpCheckResult:
    source: str
    url: str
    status_code: int | None
    final_url: str | None
    error: str | None


def run_facet_diagnostics() -> None:
    with engine.connect() as conn:
        row = conn.execute(NULL_RATE_SQL).mappings().one()
        total = row["total"]
        print(f"\n=== % de NULL por campo (total={total}) ===")
        if total == 0:
            print("Tabela car_listings vazia neste ambiente/banco.")
            return
        for field in FACET_FIELDS:
            null_count = row.get(f"{field}_null")
            if null_count is None:
                continue
            pct = 100.0 * null_count / total
            print(f"  {field:12s}: {null_count:>8d} / {total:<8d} ({pct:5.1f}% NULL)")

        oor = conn.execute(OUT_OF_RANGE_SQL).mappings().one()
        print("\n=== Valores fora de faixa plausível ===")
        print(f"  year fora de [1900,2100]:        {oor['year_out_of_range']}")
        print(f"  mileage_km fora de [0,1_500_000]: {oor['mileage_out_of_range']}")
        print(f"  price <= 0:                       {oor['price_non_positive']}")

        states = conn.execute(STATE_DISTINCT_SQL).mappings().all()
        print(f"\n=== Distinct `state` (top 40 por volume) — checar grafias divergentes (ex. 'SP' vs 'sp' vs 'São Paulo') ===")
        for r in states:
            print(f"  {r['state']!r:20s} n={r['n']}")


def run_http_liveness_probe(sample_size: int) -> None:
    import requests

    print(f"\n=== Amostra HTTP real (sample_size={sample_size} por fonte) ===")
    print("Objetivo: observar status_code/redirect hoje para inferir a assinatura de 'anúncio encerrado' por marketplace.")
    print("Webmotors NÃO incluído (PerimeterX bloqueia requests simples — ver docs/DESIGN_BUSCAR_AGORA.md).\n")

    with engine.connect() as conn:
        for source in SOURCES_TO_CHECK:
            rows = conn.execute(SAMPLE_URLS_SQL, {"source": source, "n": sample_size}).mappings().all()
            if not rows:
                print(f"[{source}] nenhuma linha amostrada (fonte sem listings no banco?)")
                continue
            print(f"[{source}] {len(rows)} URLs amostradas:")
            for r in rows:
                result = _check_url(source, r["url"])
                print(
                    f"    status={result.status_code!s:<5} "
                    f"redirected_to_different_url={result.final_url != result.url if result.final_url else 'n/a'} "
                    f"error={result.error or '-'} "
                    f"url={result.url}"
                )


def _check_url(source: str, url: str) -> HttpCheckResult:
    import requests

    try:
        resp = requests.get(url, timeout=10, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        return HttpCheckResult(
            source=source,
            url=url,
            status_code=resp.status_code,
            final_url=resp.url,
            error=None,
        )
    except requests.RequestException as exc:
        return HttpCheckResult(source=source, url=url, status_code=None, final_url=None, error=str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=8, help="Quantas URLs amostrar por marketplace (default 8)")
    parser.add_argument("--skip-http", action="store_true", help="Pula a checagem HTTP real, roda só os SELECTs de diagnóstico")
    args = parser.parse_args()

    run_facet_diagnostics()
    if not args.skip_http:
        run_http_liveness_probe(args.sample_size)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
