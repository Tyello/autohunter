from __future__ import annotations

from typing import Callable

from app.services.fipe_api_client import FipeApiClient, FipeApiError


def crawl_latest_fipe_prices(
    client: FipeApiClient,
    *,
    limit_brands: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    def progress(msg: str) -> None:
        if on_progress is not None:
            on_progress(msg)

    rows: list[dict] = []

    ref = client.get_latest_reference_table()
    reference_code = ref["Codigo"]

    brands = client.get_brands(reference_code)
    if limit_brands is not None:
        brands = brands[:limit_brands]

    for brand in brands:
        brand_code = brand["Value"]
        brand_name = brand["Label"]

        try:
            models = client.get_models(reference_code, brand_code)
        except FipeApiError as exc:
            progress(f"erro em {brand_name}: {exc}")
            continue

        model_count = 0
        for model in models:
            model_code = model["Value"]
            model_name = model["Label"]

            try:
                years = client.get_model_years(reference_code, brand_code, model_code)
            except FipeApiError as exc:
                progress(f"erro em {brand_name}/{model_name}: {exc}")
                continue

            for year_entry in years:
                value = year_entry["Value"]
                year_str, fuel_code = value.split("-", 1)

                try:
                    price = client.get_price(
                        reference_code=reference_code,
                        brand_code=brand_code,
                        model_code=model_code,
                        model_year=int(year_str),
                        fuel_code=fuel_code,
                    )
                except FipeApiError as exc:
                    progress(f"erro em {brand_name}/{model_name}/{year_str}: {exc}")
                    continue

                rows.append(
                    {
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
                )

            model_count += 1

        progress(f"{brand_name}: {model_count}/{len(models)} modelos")

    return rows
