from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from app.core.settings import settings
from app.services.fipe_api_client import FipeApiClient, FipeApiError


def _run_call(client_factory: Callable[[], FipeApiClient], fn_name: str, *args):
    """Roda 1 chamada de API em uma instância própria do client (própria Session).
    Nunca propaga exceção — isola falha por task, conforme spec 003 Etapa 4."""
    client = client_factory()
    try:
        result = getattr(client, fn_name)(*args)
        return result, None
    except FipeApiError as exc:
        return None, str(exc)
    except Exception as exc:  # nunca deve derrubar as demais tasks do pool
        return None, str(exc)


def crawl_latest_fipe_prices(
    client_factory: Callable[[], FipeApiClient],
    *,
    limit_brands: int | None = None,
    concurrency: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Varre o catálogo FIPE completo em 4 rodadas com dependência estrita entre elas
    (cada rodada usa os códigos retornados pela anterior). Rodadas 2-4 paralelizam
    via ThreadPoolExecutor, cada task usando sua própria instância de FipeApiClient
    (própria Session) obtida de client_factory — todas compartilham o mesmo
    FipeRateLimiter se a factory assim as construir, preservando o teto agregado de
    requisições/segundo.

    Quebra de compatibilidade intencional (spec 003): o parâmetro passa a ser
    `client_factory: Callable[[], FipeApiClient]` em vez de `client: FipeApiClient`.
    """
    workers = max(1, int(concurrency if concurrency is not None else settings.fipe_crawler_concurrency))
    progress_every = max(1, int(settings.fipe_crawler_progress_log_every))

    progress_lock = threading.Lock()

    def progress(msg: str) -> None:
        if on_progress is not None:
            with progress_lock:
                on_progress(msg)

    coordinator = client_factory()
    ref = coordinator.get_latest_reference_table()
    reference_code = ref["Codigo"]

    brands = coordinator.get_brands(reference_code)
    if limit_brands is not None:
        brands = brands[:limit_brands]

    # Rodada 2: modelos por marca
    models_by_brand: dict[str, list[dict]] = {}
    models_ok_by_brand: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_run_call, client_factory, "get_models", reference_code, brand["Value"]): brand
            for brand in brands
        }
        for fut in as_completed(future_map):
            brand = future_map[fut]
            result, error = fut.result()
            if error is not None:
                progress(f"erro em {brand['Label']}: {error}")
                models_by_brand[brand["Value"]] = []
                models_ok_by_brand[brand["Value"]] = False
            else:
                models_by_brand[brand["Value"]] = result or []
                models_ok_by_brand[brand["Value"]] = True

    model_pairs = [
        (brand, model)
        for brand in brands
        for model in models_by_brand.get(brand["Value"], [])
    ]

    # Rodada 3: anos por (marca, modelo)
    years_by_pair: dict[tuple[str, str], list[dict]] = {}
    years_ok_count_by_brand: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                _run_call, client_factory, "get_model_years", reference_code, brand["Value"], model["Value"]
            ): (brand, model)
            for brand, model in model_pairs
        }
        for fut in as_completed(future_map):
            brand, model = future_map[fut]
            result, error = fut.result()
            key = (brand["Value"], model["Value"])
            if error is not None:
                progress(f"erro em {brand['Label']}/{model['Label']}: {error}")
                years_by_pair[key] = []
            else:
                years_by_pair[key] = result or []
                years_ok_count_by_brand[brand["Value"]] = years_ok_count_by_brand.get(brand["Value"], 0) + 1

    for brand in brands:
        if models_ok_by_brand.get(brand["Value"]):
            total_models = len(models_by_brand.get(brand["Value"], []))
            ok_models = years_ok_count_by_brand.get(brand["Value"], 0)
            progress(f"{brand['Label']}: {ok_models}/{total_models} modelos")

    # Rodada 4: preço por combinação (marca, modelo, ano-combustível) — rodada dominante
    combos = [
        (brand, model, year_entry)
        for brand, model in model_pairs
        for year_entry in years_by_pair.get((brand["Value"], model["Value"]), [])
    ]
    total_combos = len(combos)

    def _price_call(brand: dict, model: dict, year_entry: dict):
        year_str, fuel_code = year_entry["Value"].split("-", 1)
        return _run_call_price(
            client_factory, reference_code, brand["Value"], model["Value"], int(year_str), fuel_code
        )

    rows: list[dict] = []
    rows_lock = threading.Lock()
    completed_lock = threading.Lock()
    completed_count = 0
    start_time = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_price_call, brand, model, year_entry): (brand, model, year_entry)
            for brand, model, year_entry in combos
        }
        for fut in as_completed(future_map):
            brand, model, year_entry = future_map[fut]
            price, error = fut.result()

            with completed_lock:
                completed_count += 1
                n = completed_count

            if error is not None:
                year_str = year_entry["Value"].split("-", 1)[0]
                progress(f"erro em {brand['Label']}/{model['Label']}/{year_str}: {error}")
            else:
                row = {
                    # mes_referencia omitido de proposito: o campo MesReferencia da API FIPE
                    # vem em formato "agosto/2026", nao "YYYY-MM" (o que normalize_external_fipe_row
                    # exige via regex). Deixamos o adapter usar o reference_month passado por
                    # run_monthly_fipe_sync como fallback.
                    "tipo_veiculo": "car",
                    "marca": price.get("Marca"),
                    "modelo": price.get("Modelo"),
                    "ano": price.get("AnoModelo"),
                    "combustivel": price.get("Combustivel"),
                    "codigo_fipe": price.get("CodigoFipe"),
                    "valor": price.get("Valor"),
                }
                with rows_lock:
                    rows.append(row)

            if total_combos and (n % progress_every == 0 or n == total_combos):
                elapsed = time.monotonic() - start_time
                rate = n / elapsed if elapsed > 0 else 0.0
                remaining = total_combos - n
                eta_s = remaining / rate if rate > 0 else 0.0
                progress(
                    f"progresso: {n}/{total_combos} combinações, {elapsed:.1f}s decorridos, "
                    f"{rate:.2f} combinações/s, ETA {eta_s:.1f}s"
                )

    return rows


def _run_call_price(
    client_factory: Callable[[], FipeApiClient],
    reference_code,
    brand_code: str,
    model_code: str,
    model_year: int,
    fuel_code: str,
):
    client = client_factory()
    try:
        result = client.get_price(
            reference_code=reference_code,
            brand_code=brand_code,
            model_code=model_code,
            model_year=model_year,
            fuel_code=fuel_code,
        )
        return result, None
    except FipeApiError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, str(exc)
