from __future__ import annotations

from app.models.wishlist import Wishlist
from app.sources.types import SourcePlugin


def _wishlist_location_value(wishlist: Wishlist) -> str | None:
    """Best-effort city/state the wishlist asked for (city takes precedence)."""
    city = None
    state = None
    for f in (wishlist.filters or []):
        if not getattr(f, "is_active", True):
            continue
        if f.field == "city" and not city:
            city = f.value
        elif f.field == "state" and not state:
            state = f.value
    return city or state


def canonical_search_key(wishlist: Wishlist, plugin: SourcePlugin) -> str:
    """Canonical search key for a wishlist on a given source plugin.

    Two wishlists with identical keys will fetch the same URL, producing the
    same set of raw listings. The recurrent tick scrapes once per unique key
    and fans out matching to all active wishlists via the inverted index
    (match_listings_for_active_wishlists).

    Conservative by design: only the query field (which forms the scrape URL)
    is included. WishlistFilter post-scrape rules are NOT part of the key —
    they are applied during the fan-out matching step. When in doubt, do not
    collapse: a false negative (missed alert) is worse than a redundant scrape.

    Exception: facebook_marketplace requires a city in the URL itself (no
    location-agnostic endpoint works without hitting the login wall), so its
    key also folds in the wishlist's city/state filter when present.
    """
    if plugin.name == "facebook_marketplace":
        return plugin.build_url(wishlist.query, location=_wishlist_location_value(wishlist))
    return plugin.build_url(wishlist.query)
