from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.sources.auctions.copart import fetch_copart_lots, get_last_reason as copart_reason
from app.sources.auctions.mega import fetch_mega_lots, get_last_reason as mega_reason
from app.sources.auctions.vip import fetch_vip_lots, get_last_reason as vip_reason
from app.sources.auctions.win import fetch_win_lots, get_last_reason as win_reason
from app.sources.auctions.sodre import fetch_sodre_lots, get_last_reason as sodre_reason


@dataclass(frozen=True)
class AuctionSourceDefinition:
    key: str
    aliases: tuple[str, ...]
    label: str
    fetcher: Callable
    reason_getter: Callable
    supports_enrich: bool = False
    status: str = "experimental"


_AUCTION_SOURCES: tuple[AuctionSourceDefinition, ...] = (
    AuctionSourceDefinition(
        key="vip_auctions",
        aliases=("vip", "vip_auctions"),
        label="VIP Leilões",
        fetcher=fetch_vip_lots,
        reason_getter=vip_reason,
        supports_enrich=True,
        status="active",
    ),
    AuctionSourceDefinition(
        key="mega_auctions",
        aliases=("mega", "mega_auctions"),
        label="Mega Leilões",
        fetcher=fetch_mega_lots,
        reason_getter=mega_reason,
        supports_enrich=False,
        status="experimental",
    ),
    AuctionSourceDefinition(
        key="win_auctions",
        aliases=("win", "win_auctions"),
        label="Win Leilões",
        fetcher=fetch_win_lots,
        reason_getter=win_reason,
        supports_enrich=False,
        status="experimental",
    ),
    AuctionSourceDefinition(
        key="sodre_auctions",
        aliases=("sodre", "sodre_auctions"),
        label="Sodré Santoro",
        fetcher=fetch_sodre_lots,
        reason_getter=sodre_reason,
        supports_enrich=False,
        status="experimental",
    ),
    AuctionSourceDefinition(
        key="copart_auctions",
        aliases=("copart", "copart_auctions"),
        label="Copart",
        fetcher=fetch_copart_lots,
        reason_getter=copart_reason,
        supports_enrich=False,
        status="needs_js_or_endpoint_study",
    ),
)

_BY_KEY = {item.key: item for item in _AUCTION_SOURCES}
_BY_ALIAS = {alias.lower(): item.key for item in _AUCTION_SOURCES for alias in item.aliases}


def list_auction_sources() -> list[AuctionSourceDefinition]:
    return list(_AUCTION_SOURCES)


def list_supported_auction_source_keys() -> set[str]:
    return set(_BY_KEY)


def resolve_auction_source_alias(raw: str) -> str | None:
    return _BY_ALIAS.get((raw or "").lower())


def get_auction_source_definition(source_or_alias: str) -> AuctionSourceDefinition | None:
    key = resolve_auction_source_alias(source_or_alias)
    if not key:
        return None
    return _BY_KEY.get(key)


def render_supported_auction_sources_hint() -> str:
    aliases = [item.aliases[0] for item in _AUCTION_SOURCES]
    return f"Use: {'|'.join(aliases)}"
