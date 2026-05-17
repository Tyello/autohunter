from __future__ import annotations

from app.services.source_configs_service import get_source_config
from app.sources.auctions.registry import list_supported_auction_source_keys, resolve_auction_source_alias

_DEFAULT_ALLOWED = {"car"}
_CANON = {"car", "motorcycle", "truck", "heavy", "real_estate", "other"}
_ALIASES = {
    "automovel": "car", "automóvel": "car", "automobile": "car",
    "automoveis": "car", "automóveis": "car", "carros": "car", "cars": "car", "car": "car",
    "motos": "motorcycle", "moto": "motorcycle", "motorcycle": "motorcycle",
    "caminhao": "truck", "caminhão": "truck", "caminhoes": "truck", "caminhões": "truck", "truck": "truck",
    "pesados": "heavy", "heavy": "heavy",
    "imovel": "real_estate", "imóvel": "real_estate", "imoveis": "real_estate", "imóveis": "real_estate", "real_estate": "real_estate",
    "outros": "other", "other": "other",
}


def normalize_item_type(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    return _ALIASES.get(raw)


def _resolve(source_key: str) -> str | None:
    return resolve_auction_source_alias(source_key) or (source_key if source_key in list_supported_auction_source_keys() else None)


def get_auction_allowed_item_types(db, source_key: str) -> set[str]:
    key = _resolve(source_key)
    if not key:
        return set(_DEFAULT_ALLOWED)
    cfg = get_source_config(db, key)
    extra = getattr(cfg, "extra", None) if cfg else None
    vals = (extra or {}).get("allowed_item_types") if isinstance(extra, dict) else None
    if not isinstance(vals, list) or not vals:
        return set(_DEFAULT_ALLOWED)
    normalized = {n for n in (normalize_item_type(v) for v in vals) if n in _CANON}
    return normalized or set(_DEFAULT_ALLOWED)


def is_auction_item_type_allowed(db, source_key: str, item_type: str | None) -> bool:
    allowed = get_auction_allowed_item_types(db, source_key)
    normalized = normalize_item_type(item_type)
    if normalized is None:
        return "other" in allowed
    return normalized in allowed
