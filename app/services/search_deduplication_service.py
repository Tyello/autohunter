from __future__ import annotations

from app.models.wishlist import Wishlist
from app.sources.types import SourcePlugin


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
    """
    return plugin.build_url(wishlist.query)
