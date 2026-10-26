"""Presenca de anuncios por busca: marca `car_listings.status='inativo'` ("nao vi mais").

Reaproveita os proprios jobs de busca: ao fim de cada scrape bem-sucedido de uma busca/grupo,
compara o que veio agora com o que a mesma busca trouxe antes (`last_seen_search_key`).

Regras de seguranca (ausencia so e evidencia quando):
- a busca devolveu itens (`found > 0`) -- 0 pode ser falha de parse/bloqueio silencioso;
- a pagina NAO esta cheia (`found < page_capacity`) -- pagina cheia so mostra o topo e o anuncio
  pode ter sido empurrado para a pagina 2;
- ficou ausente `missing_runs` buscas completas seguidas.

`inativo` e reversivel: o upsert (`car_listings_repo`) devolve `status='ativo'` quando o anuncio
reaparece; este servico tambem reativa os vistos (cobre o modo incremental "cut", que nao reingere).
Diferente de `is_sold` (venda confirmada pela source, nunca reverte).

Config em `source_configs.extra["inactive_reconcile"]`; default desligado:
    {"mode": "off|dry_run|on", "page_capacity": 40, "missing_runs": 3, "stale_days": 30}
`dry_run` conta e loga, mas nunca altera `status`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.car_listing import CarListing

_MODES = ("off", "dry_run", "on")
_CHUNK = 500


@dataclass(frozen=True)
class PresenceConfig:
    mode: str = "off"
    page_capacity: int | None = None
    missing_runs: int = 3
    stale_days: int | None = None

    @property
    def enabled(self) -> bool:
        return self.mode in ("dry_run", "on")

    @property
    def writes_status(self) -> bool:
        return self.mode == "on"


def _pos_int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def parse_presence_config(extra: dict | None) -> PresenceConfig:
    raw = (extra or {}).get("inactive_reconcile") if isinstance(extra, dict) else None
    if not isinstance(raw, dict):
        return PresenceConfig()
    mode = str(raw.get("mode") or "off").strip().lower()
    if mode not in _MODES:
        mode = "off"
    return PresenceConfig(
        mode=mode,
        page_capacity=_pos_int(raw.get("page_capacity")),
        missing_runs=_pos_int(raw.get("missing_runs")) or 3,
        stale_days=_pos_int(raw.get("stale_days")),
    )


def listing_is_unavailable(listing: Any) -> bool:
    """Vendido (confirmado pela source) ou nao visto mais (`inativo`)."""
    if listing is None:
        return False
    return bool(getattr(listing, "is_sold", False)) or getattr(listing, "status", None) == "inativo"


def _chunks(items: list[str]) -> Iterable[list[str]]:
    for i in range(0, len(items), _CHUNK):
        yield items[i : i + _CHUNK]


def reconcile_search_presence(
    db: Session,
    *,
    source: str,
    search_key: str,
    seen_external_ids: Iterable[str],
    found: int,
    cfg: PresenceConfig,
) -> dict:
    stats: dict[str, Any] = {"mode": cfg.mode}
    if not cfg.enabled:
        return stats

    seen = sorted({str(x) for x in (seen_external_ids or []) if x})
    if found <= 0 or not seen:
        stats["skipped"] = "empty"
        return stats

    complete = cfg.page_capacity is not None and found < cfg.page_capacity
    stats["complete"] = complete

    reactivated = 0
    for chunk in _chunks(seen):
        reactivated += int(
            db.query(func.count(CarListing.id))
            .filter(CarListing.source == source, CarListing.external_id.in_(chunk), CarListing.status == "inativo")
            .scalar()
            or 0
        )
        db.query(CarListing).filter(CarListing.source == source, CarListing.external_id.in_(chunk)).update(
            {
                CarListing.last_seen_search_key: search_key,
                CarListing.missing_runs_count: 0,
                CarListing.status: case((CarListing.status == "inativo", "ativo"), else_=CarListing.status),
            },
            synchronize_session=False,
        )
    stats["reactivated"] = reactivated

    stats.update(missing_incremented=0, marked_inactive=0, would_mark_inactive=0)
    if not complete:
        db.flush()
        return stats

    absent = (
        db.query(CarListing)
        .filter(CarListing.source == source, CarListing.last_seen_search_key == search_key)
        .filter(CarListing.status == "ativo")
        .filter(CarListing.external_id.notin_(seen))
    )
    stats["missing_incremented"] = absent.update(
        {CarListing.missing_runs_count: CarListing.missing_runs_count + 1}, synchronize_session=False
    )

    due = (
        db.query(CarListing)
        .filter(CarListing.source == source, CarListing.last_seen_search_key == search_key)
        .filter(CarListing.status == "ativo")
        .filter(CarListing.missing_runs_count >= cfg.missing_runs)
    )
    if cfg.writes_status:
        stats["marked_inactive"] = due.update({CarListing.status: "inativo"}, synchronize_session=False)
    else:
        stats["would_mark_inactive"] = int(due.count())
    db.flush()
    return stats


def mark_stale_listings_inactive(
    db: Session,
    *,
    source: str,
    cfg: PresenceConfig,
    now: datetime | None = None,
) -> dict:
    """Rede de seguranca: anuncios nao vistos ha mais de `stale_days` (cobre o legado sem
    `last_seen_search_key` e buscas que nenhuma wishlist roda mais). Roda so apos run bem-sucedido."""
    stats: dict[str, Any] = {"mode": cfg.mode, "marked_inactive": 0, "would_mark_inactive": 0}
    if not cfg.enabled:
        return stats
    if cfg.stale_days is None:
        stats["skipped"] = "no_stale_days"
        return stats

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=cfg.stale_days)
    stale = (
        db.query(CarListing)
        .filter(CarListing.source == source, CarListing.status == "ativo")
        .filter(CarListing.last_seen_at < cutoff)
    )
    if cfg.writes_status:
        stats["marked_inactive"] = stale.update({CarListing.status: "inativo"}, synchronize_session=False)
    else:
        stats["would_mark_inactive"] = int(stale.count())
    db.flush()
    return stats
