"""
Micro-benchmark for match_listings_for_wishlists with and without cand_map.

Runs entirely in-memory — no DB required.  Use this to quantify the
tokenisation-reduction from the cand_map optimisation.

Usage:
    python scripts/bench_matching.py
    python scripts/bench_matching.py --wishlists 50 --listings 200 --iters 5
"""
from __future__ import annotations

import argparse
import time
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

# ---------------------------------------------------------------------------
# Synthetic objects (no ORM / DB)
# ---------------------------------------------------------------------------

def _w(query: str, filters=()) -> Any:
    """Synthetic Wishlist-like object."""
    wid = uuid.uuid4()
    f_objs = [SimpleNamespace(field=f, operator=op, value=v) for f, op, v in filters]
    return SimpleNamespace(
        id=wid,
        query=query,
        name=None,
        filters=f_objs,
    )


def _l(title: str, price: float = 50000, year: int = 2015) -> Any:
    """Synthetic CarListing-like object."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        title=title,
        location="São Paulo, SP",
        url=f"https://example.com/{uuid.uuid4()}",
        source="olx",
        price=Decimal(str(price)),
        year=year,
        is_sold=False,
        color=None,
        city=None,
        state=None,
        seller_type=None,
        body_type=None,
        mileage_km=None,
        doors=None,
    )


# ---------------------------------------------------------------------------
# Build synthetic dataset
# ---------------------------------------------------------------------------

_MAKES = ["honda", "toyota", "fiat", "volkswagen", "chevrolet", "ford", "hyundai"]
_MODELS = ["civic", "corolla", "strada", "gol", "onix", "fiesta", "hb20", "ka", "clio"]


def _make_wishlists(n: int) -> list[Any]:
    out = []
    for i in range(n):
        make = _MAKES[i % len(_MAKES)]
        model = _MODELS[i % len(_MODELS)]
        q = f"{make} {model}"
        filters: list[tuple] = []
        if i % 3 == 0:
            filters.append(("price", "lte", str(40000 + (i % 5) * 10000)))
        if i % 5 == 0:
            filters.append(("year", "gte", str(2010 + i % 10)))
        out.append(_w(q, filters))
    return out


def _make_listings(n: int) -> list[Any]:
    out = []
    for i in range(n):
        make = _MAKES[i % len(_MAKES)]
        model = _MODELS[(i + 2) % len(_MODELS)]
        year = 2005 + (i % 18)
        price = 20000 + (i % 80) * 1000
        title = f"{make.capitalize()} {model.capitalize()} {year}"
        out.append(_l(title, price=price, year=year))
    return out


def _build_cand_map(wishlists: list[Any], listings: list[Any], density: float = 0.3) -> dict:
    """
    Synthetic candidate map: each listing maps to ~density fraction of wishlists.
    Simulates what the real inverted index would return (sparse selection).
    """
    import random
    rng = random.Random(42)
    wids = [w.id for w in wishlists]
    n_cands = max(1, int(len(wids) * density))
    return {l.id: rng.sample(wids, min(n_cands, len(wids))) for l in listings}


# ---------------------------------------------------------------------------
# Run benchmark
# ---------------------------------------------------------------------------

def bench(*, n_wishlists: int, n_listings: int, iters: int) -> None:
    from app.services.matching_service import match_listings_for_wishlists, _build_listing_ctx

    wishlists = _make_wishlists(n_wishlists)
    listings = _make_listings(n_listings)
    cand_map = _build_cand_map(wishlists, listings, density=0.3)

    n_pairs_full = n_wishlists * n_listings
    n_pairs_cand = sum(len(wids) for wids in cand_map.values())
    print(f"\nDataset: {n_wishlists} wishlists × {n_listings} listings")
    print(f"  Full pairs:      {n_pairs_full:,}")
    print(f"  Candidate pairs: {n_pairs_cand:,}  ({100*n_pairs_cand/n_pairs_full:.1f}% of full)")
    print(f"  Iterations: {iters}")

    # --- without cand_map (baseline) ---
    t0 = time.perf_counter()
    for _ in range(iters):
        match_listings_for_wishlists(wishlists, listings)
    t_full = (time.perf_counter() - t0) / iters * 1000

    # --- with cand_map (optimised) ---
    t0 = time.perf_counter()
    for _ in range(iters):
        match_listings_for_wishlists(wishlists, listings, cand_map=cand_map)
    t_cand = (time.perf_counter() - t0) / iters * 1000

    speedup = t_full / t_cand if t_cand > 0 else float("inf")
    print(f"\nResults (avg over {iters} iters):")
    print(f"  Without cand_map: {t_full:.2f} ms")
    print(f"  With    cand_map: {t_cand:.2f} ms")
    print(f"  Speedup:          {speedup:.2f}×")

    # --- tokenisation count via _build_listing_ctx ---
    # _build_listing_ctx is called once per match_listings_for_wishlists invocation
    # regardless of cand_map. Savings come from skipping pair evaluations, not from
    # reducing calls to _build_listing_ctx itself.
    #
    # Tokenisation calls (tokens() + _extract_year()) scale as:
    #   Without cand_map: N_listings (precomputed once) + N_pairs semantic hay recomputes
    #   With    cand_map: N_listings (precomputed once) + N_candidate_pairs semantic recomputes
    #
    # Primary saving = skipped filter+text checks on non-candidate pairs:
    print(f"\nPair evaluations skipped by cand_map: {n_pairs_full - n_pairs_cand:,}")
    print(f"  ({100*(n_pairs_full - n_pairs_cand)/n_pairs_full:.1f}% reduction in filter+text checks)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wishlists", type=int, default=100)
    parser.add_argument("--listings", type=int, default=150)
    parser.add_argument("--iters", type=int, default=5)
    args = parser.parse_args()
    bench(n_wishlists=args.wishlists, n_listings=args.listings, iters=args.iters)
