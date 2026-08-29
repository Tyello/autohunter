from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.fipe_lookup_request import FipeLookupRequest
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.fipe_api_client import FipeApiClient, FipeApiError
from app.services.fipe_catalog_resolver_service import _ensure_month, resolve_listing_to_fipe_candidates, important_vehicle_tokens
from app.services.fipe_external_pipeline_adapter import normalize_external_fipe_row
from app.services.fipe_monthly_sync_service import upsert_fipe_catalog_entries
from app.services import system_logs_service

# Sentinel para distinguir "parâmetro year não passado" de "year=None"
_UNSET = object()

# Constante conforme PREM-01 da spec
MAX_BOOTSTRAP_MODEL_CANDIDATES = 25


def _match_fipe_catalog_item(items: list[dict], query_text: str, *, label_key: str = "Label") -> dict | None:
    """
    Encontra o item da lista cuja label contém todos os tokens do query_text,
    com o mínimo de "extra tokens" (tokens na label que não estão no query).
    Se houver empate, retorna o primeiro da lista.
    Se nenhum item contém todos os tokens do query, retorna None.

    Tokenização usa important_vehicle_tokens(texto) para extrair palavras-chave.
    """
    if not items or not query_text:
        return None

    query_tokens = important_vehicle_tokens(query_text)
    if not query_tokens:
        return None

    best_item = None
    best_extra_count = float("inf")

    for item in items:
        label = item.get(label_key, "")
        label_tokens = important_vehicle_tokens(label)

        # Verificar se label contém todos os tokens do query
        if not query_tokens.issubset(label_tokens):
            continue

        # Contar tokens extras na label
        extra_tokens = label_tokens - query_tokens
        extra_count = len(extra_tokens)

        # Preferir item com menos tokens extras; primeiro da lista em caso de empate
        if extra_count < best_extra_count:
            best_extra_count = extra_count
            best_item = item

    return best_item


def _match_all_fipe_catalog_items(items: list[dict], query_text: str, *, label_key: str = "Label") -> list[dict]:
    """
    Retorna TODOS os items cujo token-set (via important_vehicle_tokens) contém query_tokens
    (issubset), ordenados por (menos tokens extras primeiro, depois ordem original da lista),
    truncados em MAX_BOOTSTRAP_MODEL_CANDIDATES. Lista vazia se query_tokens vazio ou nenhum match.

    Reaproveita a MESMA lógica de containment/desempate de _match_fipe_catalog_item (não duplicar
    a normalização — usa important_vehicle_tokens já utilizado por ela), mas retornando todos os
    matches em vez de só o primeiro.
    """
    if not items or not query_text:
        return []

    query_tokens = important_vehicle_tokens(query_text)
    if not query_tokens:
        return []

    matching_items = []

    for idx, item in enumerate(items):
        label = item.get(label_key, "")
        label_tokens = important_vehicle_tokens(label)

        # Verificar se label contém todos os tokens do query
        if not query_tokens.issubset(label_tokens):
            continue

        # Contar tokens extras na label
        extra_tokens = label_tokens - query_tokens
        extra_count = len(extra_tokens)

        # Armazenar tupla: (extra_count, índice original, item)
        matching_items.append((extra_count, idx, item))

    # Ordenar por (extra_count, índice original) — menos extras primeiro, depois ordem original
    matching_items.sort(key=lambda x: (x[0], x[1]))

    # Extrair os items e truncar em MAX_BOOTSTRAP_MODEL_CANDIDATES
    result = [item for _, _, item in matching_items[:MAX_BOOTSTRAP_MODEL_CANDIDATES]]

    return result


def _resolve_fipe_brand_and_models(
    client: FipeApiClient, *, make: str, model: str
) -> tuple[dict, list[dict], int] | None:
    """
    Resolve brand and multiple model candidates from FIPE API for the given make and model strings.

    Steps:
    1. Get the latest reference table and extract reference_code.
    2. Get brands list and match the make using _match_fipe_catalog_item.
       If no brand match -> return None (do NOT call get_models).
    3. Get models list for the matched brand and find all matching candidates using _match_all_fipe_catalog_items.
       If candidates list is empty -> return None.
    4. Return (brand, candidates, reference_code).

    Note: get_latest_reference_table/get_brands/get_models são cacheados por TTL a nível de
    client (FipeApiClient._catalog_cache — ver PREM cache), então chamadas repetidas para a
    mesma marca/modelo dentro da janela de TTL não geram nova requisição externa.

    Propagates FipeApiError from client calls without catching.
    """
    # Step 1: Get reference table
    reference_table = client.get_latest_reference_table()
    reference_code = reference_table["Codigo"]

    # Step 2: Get brands and match make
    brands = client.get_brands(reference_code)
    brand = _match_fipe_catalog_item(brands, make)
    if brand is None:
        return None

    # Step 3: Get models and match all candidates for model
    models = client.get_models(reference_code, brand["Value"])
    candidates = _match_all_fipe_catalog_items(models, model)
    if not candidates:
        return None

    # Step 4: Return resolved items
    return (brand, candidates, reference_code)


def _bootstrap_fipe_catalog_entries_for_year(
    db: Session,
    client: FipeApiClient,
    *,
    brand: dict,
    model_candidates: list[dict],
    reference_code: int,
    year: int,
    model_years_cache: dict[str, list[dict]],
) -> int:
    """
    Bootstrap FIPE catalog entries for a given year across all model candidates.

    For each model candidate in order (already sorted by relevance from _match_all_fipe_catalog_items):
      1. Check cache: if model["Value"] not in model_years_cache, fetch via get_model_years and cache it.
      2. For each year variant matching the target year (may be multiple fuel types — PREM-03),
         fetch price and create a catalog entry.

    Returns count of entries created/upserted.

    Propagates FipeApiError from client calls without catching (fail-fast, PREM-02).
    """
    created = 0
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    for model_item in model_candidates:
        model_value = model_item["Value"]

        # Step 1-2: Check cache or fetch model years
        if model_value not in model_years_cache:
            model_years_cache[model_value] = client.get_model_years(reference_code, brand["Value"], model_value)

        years_for_model = model_years_cache[model_value]

        # Step 3: Find all year variants matching target year (PREM-03 — all fuel types)
        matches = [
            y for y in (years_for_model or [])
            if str(y.get("Value", "")).split("-", 1)[0] == str(year)
        ]

        # Step 4: For each fuel variant, create an entry
        for year_item in matches:
            value = str(year_item.get("Value") or "")
            fuel_code = value.split("-", 1)[1] if "-" in value else value

            # Get price data
            price_data = client.get_price(
                reference_code=reference_code,
                brand_code=brand["Value"],
                model_code=model_value,
                model_year=year,
                fuel_code=fuel_code,
            )

            # Build raw row
            raw_row = {
                "tipo_veiculo": "car",
                "marca": price_data.get("Marca"),
                "modelo": price_data.get("Modelo"),
                "ano": price_data.get("AnoModelo"),
                "combustivel": price_data.get("Combustivel"),
                "codigo_fipe": price_data.get("CodigoFipe"),
                "valor": price_data.get("Valor"),
                "codigo_marca": brand["Value"],
                "codigo_modelo": model_value,
                "codigo_ano": value,
            }

            # Normalize
            normalized = normalize_external_fipe_row(raw_row, reference_month=current_month)
            if normalized is None:
                raise FipeApiError("resposta da API FIPE não pôde ser normalizada durante bootstrap")

            # Upsert
            upsert_fipe_catalog_entries(db, [normalized], reference_month=current_month, source="on_demand_bootstrap")
            created += 1

    return created


def _extract_year_bounds(filters: list[WishlistFilter]) -> tuple[int | None, int | None]:
    """
    Extrai os limites de ano (gte, lte) dos filtros de wishlist.

    Retorna uma tupla (gte, lte) onde cada valor é um int ou None.
    Se o valor não puder ser convertido para int, é tratado como None.
    """
    gte_value = None
    lte_value = None
    for flt in filters:
        if getattr(flt, "field", None) != "year":
            continue
        operator = getattr(flt, "operator", None)
        if operator == "gte":
            gte_value = flt.value
        elif operator == "lte":
            lte_value = flt.value

    gte_year = None
    if gte_value is not None:
        try:
            gte_year = int(str(gte_value).strip())
        except (ValueError, TypeError):
            gte_year = None

    lte_year = None
    if lte_value is not None:
        try:
            lte_year = int(str(lte_value).strip())
        except (ValueError, TypeError):
            lte_year = None

    return (gte_year, lte_year)


def _resolve_target_years(
    gte: int | None, lte: int | None, current_year: int, max_years: int
) -> list[int]:
    """
    Resolve os anos alvo a partir dos limites gte/lte.

    Conforme spec:
    - gte is None and lte is None -> [] (sem filtro de ano)
    - Só gte -> range = [gte, current_year] (se gte > current_year, range = [current_year, gte]).
      Âncora = current_year.
    - Só lte -> range = [lte - max_years + 1, lte]. Âncora = lte.
    - Ambos -> range = [min(gte,lte), max(gte,lte)]. Âncora = min(max(current_year, gte), lte).
    - Se len(range) <= max_years: retorna o range inteiro, ordem crescente.
    - Senão: ordena os anos do range por (abs(ano - âncora), -ano) crescente, pega os
      max_years primeiros, devolve em ordem crescente.
    """
    max_years = max(1, max_years)  # Garantir max_years >= 1

    if gte is None and lte is None:
        return []

    if gte is not None and lte is not None:
        # Ambos definidos
        range_min = min(gte, lte)
        range_max = max(gte, lte)
        anchor = min(max(current_year, gte), lte)
        years = list(range(range_min, range_max + 1))
    elif gte is not None:
        # Só gte
        anchor = current_year
        range_min = min(gte, current_year)
        range_max = max(gte, current_year)
        years = list(range(range_min, range_max + 1))
    else:
        # Só lte
        anchor = lte
        range_min = max(lte - max_years + 1, 1900)
        range_max = lte
        years = list(range(range_min, range_max + 1))

    # Se o range é pequeno, retorna tudo
    if len(years) <= max_years:
        return sorted(years)

    # Senão, ordena por distância da âncora e pega os max_years primeiros
    sorted_by_distance = sorted(years, key=lambda y: (abs(y - anchor), -y))
    result = sorted_by_distance[:max_years]
    return sorted(result)


def _build_pseudo_listing(wishlist: Wishlist, filters: list[WishlistFilter], db: Session, year=_UNSET) -> SimpleNamespace:
    tokens = (wishlist.query or "").split()

    # Determinar make e model: primeiro tenta detectar marca conhecida no catálogo
    if not tokens:
        make = model = None
    else:
        # Obter marcas conhecidas do catálogo (normalizadas)
        known_brands = {}  # normalized_name -> original_capitalization
        for (brand_name,) in db.query(FipeCatalogEntry.brand_name).distinct().all():
            if brand_name:
                normalized = brand_name.strip().lower()
                if normalized not in known_brands:
                    known_brands[normalized] = brand_name

        # Buscar a maior sequência contígua de tokens que bate com uma marca conhecida
        found_brand_idx = -1
        found_brand_len = 0
        found_brand_original = None

        for start_idx in range(len(tokens)):
            for end_idx in range(start_idx, len(tokens)):
                # Construir sequência de tokens do índice start_idx até end_idx (inclusive)
                seq_tokens = tokens[start_idx:end_idx + 1]
                seq_normalized = " ".join(t.strip().lower() for t in seq_tokens)

                # Se essa sequência bate com uma marca conhecida
                if seq_normalized in known_brands:
                    seq_len = len(seq_tokens)
                    # Guardar a sequência mais longa encontrada (ou a primeira se tiver o mesmo tamanho)
                    if seq_len > found_brand_len:
                        found_brand_len = seq_len
                        found_brand_idx = start_idx
                        found_brand_original = known_brands[seq_normalized]

        if found_brand_idx >= 0 and found_brand_original:
            # Encontrou marca conhecida
            make = found_brand_original
            # Model = tokens antes + tokens depois da marca (excluindo os consumidos)
            before = tokens[:found_brand_idx]
            after = tokens[found_brand_idx + found_brand_len:]
            model_tokens = before + after
            model = " ".join(model_tokens) if model_tokens else None
            if model is None or model.strip() == "":
                model = make  # Se não houve tokens restantes, model = make
        else:
            # Fallback: heurística legada (primeiro token = make)
            if len(tokens) == 1:
                make = model = tokens[0]
            else:
                make = tokens[0]
                model = " ".join(tokens[1:])

    # Determinar year
    if year is _UNSET:
        # Usar comportamento padrão: extrair de filters
        gte_value, lte_value = _extract_year_bounds(filters)
        raw_year = gte_value if gte_value is not None else lte_value
        year = None
        if raw_year is not None:
            try:
                year = int(str(raw_year).strip())
            except (ValueError, TypeError):
                year = None
    else:
        # Usar o valor recebido diretamente (pode ser None)
        pass

    return SimpleNamespace(make=make, model=model, year=year, version=None, fuel_type=None, id=wishlist.id)


def enqueue_fipe_lookup_for_wishlist(db: Session, wishlist: Wishlist) -> FipeLookupRequest | None:
    if not settings.fipe_lookup_enabled:
        return None
    try:
        existing = (
            db.query(FipeLookupRequest)
            .filter(FipeLookupRequest.wishlist_id == wishlist.id, FipeLookupRequest.status == "pending")
            .first()
        )
        if existing:
            return None
        request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
        db.add(request)
        db.commit()
        db.refresh(request)
        return request
    except Exception as exc:
        print(f"[fipe_on_demand_lookup] enqueue_failed wishlist_id={wishlist.id} exc_type={type(exc).__name__} err={exc}")
        try:
            system_logs_service.log(db, "error", "fipe_lookup", "enqueue_failed", {"wishlist_id": str(wishlist.id), "error": str(exc)})
        except Exception:
            pass
        db.rollback()
        return None


def _mark_skipped(db: Session, request: FipeLookupRequest) -> str:
    request.status = "skipped"
    request.processed_at = datetime.now(timezone.utc)
    db.commit()
    return "skipped"


def _is_fresh(entry: FipeCatalogEntry) -> bool:
    updated_at = entry.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.fipe_lookup_freshness_days)
    return updated_at >= cutoff


def _find_target_year(years: list[dict], entry: FipeCatalogEntry) -> dict | None:
    if entry.model_year is None:
        return None
    year_matches = [item for item in (years or []) if str(item.get("Value", "")).split("-", 1)[0] == str(entry.model_year)]
    if not year_matches:
        return None
    if entry.fuel:
        fuel_norm = entry.fuel.strip().lower()
        for item in year_matches:
            if fuel_norm in str(item.get("Label", "")).lower():
                return item
    return year_matches[0]


def _refresh_fipe_catalog_entry(db: Session, entry: FipeCatalogEntry, client: FipeApiClient | None = None) -> None:
    if not entry.brand_code or not entry.model_code:
        raise FipeApiError(
            f"brand_code/model_code ausentes no candidato catalog_entry_id={entry.id}; refresh direcionado inviável"
        )

    client = client or FipeApiClient()
    reference_table = client.get_latest_reference_table()
    reference_code = reference_table.get("Codigo")

    years = client.get_model_years(reference_code, entry.brand_code, entry.model_code)
    target = _find_target_year(years, entry)
    if target is None:
        raise FipeApiError(
            f"nenhuma combinação de ano/combustível encontrada para brand_code={entry.brand_code} "
            f"model_code={entry.model_code} model_year={entry.model_year}"
        )

    value = str(target.get("Value") or "")
    fuel_code = value.split("-", 1)[1] if "-" in value else value

    price_data = client.get_price(
        reference_code=reference_code,
        brand_code=entry.brand_code,
        model_code=entry.model_code,
        model_year=entry.model_year,
        fuel_code=fuel_code,
    )

    raw_row = {
        "tipo_veiculo": entry.vehicle_type,
        "marca": price_data.get("Marca"),
        "modelo": price_data.get("Modelo"),
        "ano": price_data.get("AnoModelo"),
        "combustivel": price_data.get("Combustivel"),
        "codigo_fipe": price_data.get("CodigoFipe"),
        "valor": price_data.get("Valor"),
    }
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    normalized = normalize_external_fipe_row(raw_row, reference_month=current_month)
    if normalized is None:
        raise FipeApiError("resposta da API FIPE não pôde ser normalizada durante refresh direcionado")

    upsert_fipe_catalog_entries(db, [normalized], reference_month=current_month, source="on_demand")


def _apply_bootstrap_api_error(
    db: Session, request: FipeLookupRequest, wishlist: Wishlist, outcomes: list[dict], year: int | None, exc: Exception
) -> str:
    """
    Handle FipeApiError during bootstrap (brand/model resolution or catalog entry creation).

    Identical to the existing `except FipeApiError` block in _process_one_fipe_lookup for refresh,
    extracted as a reusable helper:
    1. Append {"year": year, "status": "api_error", "confidence_score": None} to outcomes.
    2. Roll back database.
    3. Increment request.attempts and set request.last_error = str(exc)[:1000].
    4. If request.attempts >= settings.fipe_lookup_max_attempts: set status="failed" and processed_at.
       Otherwise: set status="pending".
    5. Log to system_logs with "api_error" as final_status.
    6. Commit database.
    7. Return "failed_final" if max attempts reached, else "failed_temp".
    """
    # 1. Append error outcome
    outcomes.append({"year": year, "status": "api_error", "confidence_score": None})

    # 2. Rollback
    db.rollback()

    # 3. Increment attempts and set error message
    request.attempts += 1
    request.last_error = str(exc)[:1000]

    # 4. Determine status
    if request.attempts >= settings.fipe_lookup_max_attempts:
        request.status = "failed"
        request.processed_at = datetime.now(timezone.utc)
    else:
        request.status = "pending"

    # 5. Log to system_logs
    try:
        system_logs_service.log(
            db,
            "info",
            "fipe_lookup",
            "fipe on-demand lookup outcome",
            payload={
                "wishlist_id": str(wishlist.id),
                "outcomes": outcomes,
                "final_status": "api_error",
            },
        )
    except Exception:
        pass

    # 6. Commit
    db.commit()

    # 7. Return outcome
    return "failed_final" if request.attempts >= settings.fipe_lookup_max_attempts else "failed_temp"


def _process_one_reactive_fipe_lookup(db: Session, client: FipeApiClient, request: FipeLookupRequest) -> str:
    """
    Caminho reativo: request.listing_make/listing_model/target_year já setados (PREM-01).
    Resolve marca/modelo e faz bootstrap pra um ano específico.

    Retorna "bootstrapped" se criou entries, "skipped" se não criou,
    ou "failed_final"/"failed_temp" em caso de erro com retry.
    """
    # Carregar wishlist
    wishlist = db.query(Wishlist).filter(Wishlist.id == request.wishlist_id).first()
    if wishlist is None:
        return _mark_skipped(db, request)

    # Tentar resolver marca/modelo
    try:
        resolved = _resolve_fipe_brand_and_models(client, make=request.listing_make, model=request.listing_model)
    except FipeApiError as exc:
        return _apply_bootstrap_api_error(db, request, wishlist, [], request.target_year, exc)

    # Se marca/modelo não resolveu
    if resolved is None:
        return _mark_skipped(db, request)

    brand, candidates, reference_code = resolved
    model_years_cache: dict[str, list[dict]] = {}

    # Tentar bootstrap pra o ano específico
    try:
        created = _bootstrap_fipe_catalog_entries_for_year(
            db, client, brand=brand, model_candidates=candidates,
            reference_code=reference_code, year=request.target_year,
            model_years_cache=model_years_cache,
        )
    except FipeApiError as exc:
        return _apply_bootstrap_api_error(db, request, wishlist, [], request.target_year, exc)

    # Decidir outcome
    if created > 0:
        request.status = "done"
        request.processed_at = datetime.now(timezone.utc)
        db.commit()
        return "bootstrapped"
    else:
        return _mark_skipped(db, request)


def _process_one_fipe_lookup(db: Session, request: FipeLookupRequest) -> str:
    """
    Process FIPE lookup request com loop sobre múltiplos anos-alvo.

    Contrato conforme spec:
    1. Carrega wishlist e filters
    2. Extrai limites de ano (gte, lte)
    3. Resolve anos-alvo de acordo com settings.fipe_lookup_year_expand_max
    4. Se nenhum ano-alvo: usa [None] para preservar behavior legado
    5. Para cada ano: builda pseudo_listing, resolve candidatos, aplica lógica de decisão
       - insufficient_data/no_match/low confidence -> "skipped_year"
       - candidato fresco -> "done"
       - candidato stale -> tenta refresh; sucesso -> "refreshed"; FipeApiError -> "api_error" + PARA loop
    6. Acumula outcomes (year, status, confidence_score)
    7. Grava outcomes em system_logs SEMPRE
    8. Decisão final:
       - Se algum outcome for "done"/"refreshed" -> final_status = "done"
       - Senão, se algum outcome for "api_error" -> aplica retry logic (attempts/last_error)
       - Senão (todos skipped_year) -> final_status = "skipped"

    Retorna outcome para contadores (done/skipped/refreshed/api_error/etc)
    """
    # 1. Carrega wishlist e filters
    wishlist = db.query(Wishlist).filter(Wishlist.id == request.wishlist_id).first()
    if wishlist is None:
        return _mark_skipped(db, request)

    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()

    # 2-3. Extrai limites e resolve anos-alvo
    gte, lte = _extract_year_bounds(filters)
    current_year = datetime.now(timezone.utc).year
    target_years = _resolve_target_years(gte, lte, current_year, settings.fipe_lookup_year_expand_max)

    # 4. Se nenhum ano-alvo: usa [None] para preservar behavior legado (sem ano)
    if not target_years:
        target_years = [None]

    # 5. Prepara para loop
    month = _ensure_month(db, None)
    outcomes = []
    final_outcome = None  # Rastreia o tipo de sucesso (done ou refreshed)

    # Bootstrap variables (Etapa 3+)
    bootstrap_attempted = False
    bootstrap_resolved = None  # Now: tuple(brand, model_candidates_list, reference_code) | None
    bootstrap_client = None
    model_years_cache: dict[str, list[dict]] = {}  # Cache por modelo, cross-year dentro do request

    # 6. Loop sobre anos-alvo (crescente)
    for year in sorted(target_years):
        pseudo_listing = _build_pseudo_listing(wishlist, filters, db, year=year)
        result = resolve_listing_to_fipe_candidates(db, listing=pseudo_listing, reference_month=month, limit=5)
        best = result.get("best_candidate")
        confidence_score = None

        # Lógica de decisão para este ano
        if result["status"] == "insufficient_data" or best is None:
            # insufficient_data ou no_match: tenta bootstrap
            if not bootstrap_attempted and pseudo_listing.make and pseudo_listing.model and year is not None:
                bootstrap_attempted = True
                bootstrap_client = FipeApiClient()
                try:
                    bootstrap_resolved = _resolve_fipe_brand_and_models(
                        bootstrap_client, make=pseudo_listing.make, model=pseudo_listing.model
                    )
                except FipeApiError as exc:
                    return _apply_bootstrap_api_error(db, request, wishlist, outcomes, year, exc)

            if bootstrap_resolved:
                brand, model_candidates, reference_code = bootstrap_resolved
                try:
                    created_count = _bootstrap_fipe_catalog_entries_for_year(
                        db, bootstrap_client, brand=brand, model_candidates=model_candidates,
                        reference_code=reference_code, year=year, model_years_cache=model_years_cache,
                    )
                except FipeApiError as exc:
                    return _apply_bootstrap_api_error(db, request, wishlist, outcomes, year, exc)
                if created_count > 0:
                    outcomes.append({"year": year, "status": "bootstrapped", "confidence_score": None})
                    if final_outcome is None:
                        final_outcome = "bootstrapped"
                    continue

            outcomes.append({"year": year, "status": "skipped_year", "confidence_score": None})
            continue

        confidence_score = best.get("confidence_score", 0)
        if confidence_score < settings.fipe_lookup_min_confidence:
            # Baixa confiança
            outcomes.append({"year": year, "status": "skipped_year", "confidence_score": confidence_score})
            continue

        # Candidato válido: tenta recuperar entry do catálogo
        try:
            catalog_entry_id = uuid.UUID(str(best["catalog_entry_id"]))
        except (ValueError, TypeError, KeyError):
            outcomes.append({"year": year, "status": "skipped_year", "confidence_score": confidence_score})
            continue

        entry = db.query(FipeCatalogEntry).filter(FipeCatalogEntry.id == catalog_entry_id).first()
        if entry is None:
            outcomes.append({"year": year, "status": "skipped_year", "confidence_score": confidence_score})
            continue

        # Entry existe: verifica se é fresco
        if _is_fresh(entry):
            # Candidato fresco -> outcome "done"
            outcomes.append({"year": year, "status": "done", "confidence_score": confidence_score})
            if final_outcome is None:
                final_outcome = "done"
            continue

        # Candidato stale -> tenta refresh
        try:
            _refresh_fipe_catalog_entry(db, entry)
            # Sucesso no refresh -> outcome "refreshed"
            outcomes.append({"year": year, "status": "refreshed", "confidence_score": confidence_score})
            # Preferir retornar "refreshed" se houver sucesso no refresh (priority over just "done")
            if final_outcome != "done":
                final_outcome = "refreshed"
            continue
        except FipeApiError as exc:
            # FipeApiError -> outcome "api_error" e PARA o loop (não tenta anos restantes)
            outcomes.append({"year": year, "status": "api_error", "confidence_score": confidence_score})
            db.rollback()
            # Incrementa attempts e determina status (failed ou pending)
            request.attempts += 1
            request.last_error = str(exc)[:1000]
            if request.attempts >= settings.fipe_lookup_max_attempts:
                request.status = "failed"
                request.processed_at = datetime.now(timezone.utc)
            else:
                request.status = "pending"
            # Grava system_logs antes de sair
            try:
                system_logs_service.log(
                    db,
                    "info",
                    "fipe_lookup",
                    "fipe on-demand lookup outcome",
                    payload={
                        "wishlist_id": str(wishlist.id),
                        "outcomes": outcomes,
                        "final_status": "api_error",
                    },
                )
            except Exception:
                pass
            db.commit()
            return "failed_final" if request.attempts >= settings.fipe_lookup_max_attempts else "failed_temp"
        except Exception as exc:
            # Outra exceção durante refresh: trata como api_error também
            outcomes.append({"year": year, "status": "api_error", "confidence_score": confidence_score})
            db.rollback()
            request.attempts += 1
            request.last_error = str(exc)[:1000]
            if request.attempts >= settings.fipe_lookup_max_attempts:
                request.status = "failed"
                request.processed_at = datetime.now(timezone.utc)
            else:
                request.status = "pending"
            try:
                system_logs_service.log(
                    db,
                    "info",
                    "fipe_lookup",
                    "fipe on-demand lookup outcome",
                    payload={
                        "wishlist_id": str(wishlist.id),
                        "outcomes": outcomes,
                        "final_status": "api_error",
                    },
                )
            except Exception:
                pass
            db.commit()
            return "failed_final" if request.attempts >= settings.fipe_lookup_max_attempts else "failed_temp"

    # 7. SEMPRE grava outcomes em system_logs (apenas se não houver api_error/exception acima)
    final_status = "done" if final_outcome else "skipped"
    try:
        system_logs_service.log(
            db,
            "info",
            "fipe_lookup",
            "fipe on-demand lookup outcome",
            payload={
                "wishlist_id": str(wishlist.id),
                "outcomes": outcomes,
                "final_status": final_status,
            },
        )
    except Exception:
        # Log é best-effort; não falha o request se system_logs falhar
        pass

    # 8. Decisão final
    if final_status == "done":
        # Algum ano foi bem-sucedido (done ou refreshed)
        request.status = "done"
        request.processed_at = datetime.now(timezone.utc)
        db.commit()
        # Retorna o outcome específico (done ou refreshed) para contadores
        return final_outcome

    # final_status == "skipped"
    return _mark_skipped(db, request)


def process_pending_fipe_lookups(db: Session, *, limit: int | None = None) -> dict:
    batch_limit = int(limit if limit is not None else settings.fipe_lookup_batch_size)
    counters = {"claimed": 0, "done": 0, "skipped": 0, "refreshed": 0, "bootstrapped": 0, "failed_temp": 0, "failed_final": 0}

    pending = (
        db.query(FipeLookupRequest)
        .filter(FipeLookupRequest.status == "pending")
        .order_by(FipeLookupRequest.created_at)
        .limit(batch_limit)
        .all()
    )

    # Client compartilhado pelas requests do caminho reativo dentro do batch: reaproveita
    # o cache TTL de marca/modelo/ano (fipe_api_client._catalog_cache) e o FipeRateLimiter
    # entre requests, em vez de recriar (e perder cache/estado de throttle) a cada request.
    reactive_client = FipeApiClient() if any(r.listing_make is not None for r in pending) else None

    for request in pending:
        request.status = "processing"
        db.commit()
        counters["claimed"] += 1
        try:
            if request.listing_make is not None:
                # Caminho reativo
                outcome = _process_one_reactive_fipe_lookup(db, reactive_client, request)
            else:
                # Caminho clássico
                outcome = _process_one_fipe_lookup(db, request)
            counters[outcome] += 1
        except Exception as exc:
            db.rollback()
            request.attempts += 1
            request.last_error = str(exc)[:1000]
            if request.attempts >= settings.fipe_lookup_max_attempts:
                request.status = "failed"
                request.processed_at = datetime.now(timezone.utc)
                counters["failed_final"] += 1
            else:
                request.status = "pending"
                counters["failed_temp"] += 1
            db.commit()

    if reactive_client is not None and hasattr(reactive_client, "cache_stats"):
        counters["fipe_cache"] = reactive_client.cache_stats()

    return counters
