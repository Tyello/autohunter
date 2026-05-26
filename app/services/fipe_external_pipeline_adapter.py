from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.services.fipe_monthly_sync_service import normalize_fipe_month, normalize_fipe_text

_ALIAS = {
    "reference_month": ["reference_month", "mes_referencia"],
    "vehicle_type": ["vehicle_type", "tipo_veiculo"],
    "brand_code": ["brand_code", "codigo_marca", "marca_codigo"],
    "brand_name": ["brand_name", "brand", "marca", "nome_marca"],
    "model_code": ["model_code", "codigo_modelo", "modelo_codigo"],
    "model_name": ["model_name", "model", "modelo", "nome_modelo"],
    "year_code": ["year_code", "codigo_ano", "ano_codigo"],
    "model_year": ["model_year", "year", "ano", "ano_modelo"],
    "fuel": ["fuel", "combustivel"],
    "fipe_code": ["fipe_code", "codigo_fipe"],
    "price": ["price", "valor", "preco", "fipe_price"],
    "currency": ["currency", "moeda"],
}


def _pick(row: dict, field: str):
    for key in _ALIAS[field]:
        if key in row:
            return row.get(key)
    return None


def _parse_price(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        price = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return price if price > 0 else None


def _parse_model_year(value):
    if value in (None, ""):
        return None
    raw = str(value).strip()
    m = re.match(r"^(\d{4})", raw)
    if m:
        return int(m.group(1))
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def normalize_external_fipe_row(row: dict, *, reference_month: str) -> dict | None:
    if not isinstance(row, dict):
        return None

    row_month = normalize_fipe_text(_pick(row, "reference_month")) or normalize_fipe_month(reference_month)
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", row_month):
        return None

    model_name = normalize_fipe_text(_pick(row, "model_name"))
    price = _parse_price(_pick(row, "price"))
    if not model_name or price is None:
        return None

    out = {
        "reference_month": row_month,
        "vehicle_type": normalize_fipe_text(_pick(row, "vehicle_type")) or "car",
        "brand_code": normalize_fipe_text(_pick(row, "brand_code")) or None,
        "brand_name": normalize_fipe_text(_pick(row, "brand_name")) or None,
        "model_code": normalize_fipe_text(_pick(row, "model_code")) or None,
        "model_name": model_name,
        "year_code": normalize_fipe_text(_pick(row, "year_code")) or None,
        "model_year": _parse_model_year(_pick(row, "model_year")),
        "fuel": normalize_fipe_text(_pick(row, "fuel")) or None,
        "fipe_code": normalize_fipe_text(_pick(row, "fipe_code")) or None,
        "price": price,
        "currency": (normalize_fipe_text(_pick(row, "currency")) or "BRL").upper(),
        "raw_payload": row,
    }
    return out


def normalize_external_fipe_rows(rows: list[dict], *, reference_month: str) -> tuple[list[dict], dict]:
    counters = {"total": len(rows or []), "normalized": 0, "skipped_invalid": 0, "skipped_missing_price": 0, "skipped_missing_model": 0}
    out = []
    month = normalize_fipe_month(reference_month)
    for row in rows or []:
        if not isinstance(row, dict):
            counters["skipped_invalid"] += 1
            continue
        if not normalize_fipe_text(_pick(row, "model_name")):
            counters["skipped_missing_model"] += 1
            continue
        if _parse_price(_pick(row, "price")) is None:
            counters["skipped_missing_price"] += 1
            continue
        normalized = normalize_external_fipe_row(row, reference_month=month)
        if normalized is None:
            counters["skipped_invalid"] += 1
            continue
        out.append(normalized)
        counters["normalized"] += 1
    return out, counters
