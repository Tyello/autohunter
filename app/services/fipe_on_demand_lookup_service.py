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
from app.services.fipe_catalog_resolver_service import _ensure_month, resolve_listing_to_fipe_candidates
from app.services.fipe_external_pipeline_adapter import normalize_external_fipe_row
from app.services.fipe_monthly_sync_service import upsert_fipe_catalog_entries
from app.services import system_logs_service

# Sentinel para distinguir "parâmetro year não passado" de "year=None"
_UNSET = object()


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


def _refresh_fipe_catalog_entry(db: Session, entry: FipeCatalogEntry) -> None:
    if not entry.brand_code or not entry.model_code:
        raise FipeApiError(
            f"brand_code/model_code ausentes no candidato catalog_entry_id={entry.id}; refresh direcionado inviável"
        )

    client = FipeApiClient()
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

    # 6. Loop sobre anos-alvo (crescente)
    for year in sorted(target_years):
        pseudo_listing = _build_pseudo_listing(wishlist, filters, db, year=year)
        result = resolve_listing_to_fipe_candidates(db, listing=pseudo_listing, reference_month=month, limit=5)
        best = result.get("best_candidate")
        confidence_score = None

        # Lógica de decisão para este ano
        if result["status"] == "insufficient_data" or best is None:
            # insufficient_data ou no_match
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
    counters = {"claimed": 0, "done": 0, "skipped": 0, "refreshed": 0, "failed_temp": 0, "failed_final": 0}

    pending = (
        db.query(FipeLookupRequest)
        .filter(FipeLookupRequest.status == "pending")
        .order_by(FipeLookupRequest.created_at)
        .limit(batch_limit)
        .all()
    )

    for request in pending:
        request.status = "processing"
        db.commit()
        counters["claimed"] += 1
        try:
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

    return counters
