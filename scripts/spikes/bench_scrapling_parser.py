#!/usr/bin/env python3
"""
Benchmark script for comparing OLX parser performance:
  (a) BeautifulSoup4 with html.parser
  (b) BeautifulSoup4 with lxml
  (c) scrapling.parser.Selector

Measures timing (median/p95 over 100+ iterations) and peak memory usage.
Operations replicate real OLX scraper logic: locate __NEXT_DATA__/RSC data,
select cards via CSS selectors, extract title/price/location/image/attributes.
"""

import json
import re
import time
import tracemalloc
from pathlib import Path
from statistics import median

from bs4 import BeautifulSoup

try:
    from scrapling.parser import Selector
except ImportError:
    Selector = None


FIXTURES_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "olx"
FIXTURES = [
    "audi_a4_avant_2019_detail.html",
    "honda_civic_coupe_2015_detail.html",
    "honda_civic_coupe_2015_detail_share_placeholder.html",
    "honda_civic_hatch_1993_detail.html",
    "search_rsc_price_nodes.html",
]

NUM_ITERATIONS = 100


def extract_rsc_json_chunks(html: str) -> list:
    """
    Extract JSON payloads from RSC streaming format (self.__next_f.push([1, "..."]))
    Mirrors app/scrapers/olx.py:386-409
    """
    chunks = []
    # Match self.__next_f.push([1, "..."])
    pattern = re.compile(r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)')
    for raw in pattern.findall(html or ""):
        try:
            decoded = json.loads(raw)
            # Parse chunk structure: "chunkId:json_data"
            m = re.match(r'^[0-9a-zA-Z]+:(.*)$', decoded, re.DOTALL)
            body = m.group(1) if m else decoded
            try:
                data = json.loads(body)
                chunks.append(data)
            except Exception:
                continue
        except Exception:
            continue
    return chunks


def extract_next_data_json(html: str) -> dict | None:
    """
    Extract __NEXT_DATA__ JSON from Next.js pages.
    Mirrors app/scrapers/olx.py:358-379
    """
    # Try <script id="__NEXT_DATA__">...</script> first
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


def extract_with_bs4_html_parser(html: str) -> dict:
    """
    Variant (a): BeautifulSoup4 with html.parser
    Replicates operations from olx.py:252,363,757
    """
    soup = BeautifulSoup(html, "html.parser")
    results = {"parser": "BS4 html.parser", "extracted": []}

    # Operation 1: Extract detail thumbnail (line 252)
    # Look for og:image in detail pages
    og_image = soup.select_one('meta[property="og:image"]')
    if og_image and og_image.get("content"):
        results["extracted"].append(og_image.get("content")[:50])

    # Operation 2: Extract __NEXT_DATA__ (line 363)
    next_data = extract_next_data_json(html)
    if next_data:
        results["extracted"].append(str(type(next_data).__name__))

    # Operation 3: Extract RSC JSON chunks
    rsc_chunks = extract_rsc_json_chunks(html)
    if rsc_chunks:
        results["extracted"].append(f"rsc_chunks:{len(rsc_chunks)}")

    # Operation 4: Fallback parse from cards (line 757)
    # Select adcard links
    cards = soup.select('a[data-testid="adcard-link"]')
    if cards:
        results["extracted"].append(f"cards:{len(cards)}")
        # Extract fields from first card
        for card in cards[:1]:
            title = card.get_text(" ", strip=True)
            if title:
                results["extracted"].append(f"title:{title[:30]}")
            # Look for price in parent container
            container = card.find_parent()
            if container:
                price_el = container.select_one(".olx-adcard__price")
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    results["extracted"].append(f"price:{price_text[:20]}")

    return results


def extract_with_bs4_lxml(html: str) -> dict:
    """
    Variant (b): BeautifulSoup4 with lxml
    Same logic as html.parser but using lxml backend
    """
    soup = BeautifulSoup(html, "lxml")
    results = {"parser": "BS4 lxml", "extracted": []}

    # Operation 1: Extract detail thumbnail
    og_image = soup.select_one('meta[property="og:image"]')
    if og_image and og_image.get("content"):
        results["extracted"].append(og_image.get("content")[:50])

    # Operation 2: Extract __NEXT_DATA__
    next_data = extract_next_data_json(html)
    if next_data:
        results["extracted"].append(str(type(next_data).__name__))

    # Operation 3: Extract RSC JSON chunks
    rsc_chunks = extract_rsc_json_chunks(html)
    if rsc_chunks:
        results["extracted"].append(f"rsc_chunks:{len(rsc_chunks)}")

    # Operation 4: Fallback parse from cards
    cards = soup.select('a[data-testid="adcard-link"]')
    if cards:
        results["extracted"].append(f"cards:{len(cards)}")
        for card in cards[:1]:
            title = card.get_text(" ", strip=True)
            if title:
                results["extracted"].append(f"title:{title[:30]}")
            container = card.find_parent()
            if container:
                price_el = container.select_one(".olx-adcard__price")
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    results["extracted"].append(f"price:{price_text[:20]}")

    return results


def extract_with_scrapling(html: str) -> dict:
    """
    Variant (c): scrapling.parser.Selector
    Same logic using CSS selectors via Scrapling
    """
    if Selector is None:
        return {"parser": "Scrapling", "error": "not installed"}

    results = {"parser": "Scrapling Selector", "extracted": []}

    try:
        selector = Selector(html)

        # Operation 1: Extract detail thumbnail
        og_image_url = selector.css('meta[property="og:image"]::attr(content)').get()
        if og_image_url:
            results["extracted"].append(og_image_url[:50])

        # Operation 2: Extract __NEXT_DATA__
        next_data_str = selector.css('script#__NEXT_DATA__::text').get()
        if next_data_str:
            try:
                next_data = json.loads(next_data_str)
                results["extracted"].append(str(type(next_data).__name__))
            except Exception:
                pass

        # Operation 3: Extract RSC JSON chunks
        rsc_chunks = extract_rsc_json_chunks(html)
        if rsc_chunks:
            results["extracted"].append(f"rsc_chunks:{len(rsc_chunks)}")

        # Operation 4: Extract cards via CSS selector
        cards = selector.css('a[data-testid="adcard-link"]')
        if cards:
            card_list = cards.getall()
            results["extracted"].append(f"cards:{len(card_list)}")
            # Extract from first card
            if card_list:
                first_card = Selector(card_list[0])
                title = first_card.css('::text').get()
                if title:
                    results["extracted"].append(f"title:{title[:30]}")
                # Price in parent container
                container = first_card.css('..::text').get()
                if container and "R$" in container:
                    results["extracted"].append(f"price:{container[:20]}")

    except Exception as e:
        results["error"] = str(e)

    return results


def benchmark_fixture(fixture_name: str, num_iterations: int = NUM_ITERATIONS) -> dict:
    """
    Benchmark a single fixture with all 3 parser variants.
    Returns dict mapping variant name to {median_ms, p95_ms, peak_mb}
    """
    html_path = FIXTURES_DIR / fixture_name
    if not html_path.exists():
        raise FileNotFoundError(f"Fixture not found: {html_path}")

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    results = {}

    # Variant (a): BS4 html.parser
    times_a = []
    peak_mem_a = 0
    for _ in range(num_iterations):
        tracemalloc.start()
        t0 = time.perf_counter()
        extract_with_bs4_html_parser(html)
        t1 = time.perf_counter()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        times_a.append(t1 - t0)
        peak_mem_a = max(peak_mem_a, peak)

    results["BS4 html.parser"] = {
        "median_ms": median(times_a) * 1000,
        "p95_ms": sorted(times_a)[int(len(times_a) * 0.95)] * 1000,
        "peak_mb": peak_mem_a / 1024 / 1024,
    }

    # Variant (b): BS4 lxml
    times_b = []
    peak_mem_b = 0
    for _ in range(num_iterations):
        tracemalloc.start()
        t0 = time.perf_counter()
        extract_with_bs4_lxml(html)
        t1 = time.perf_counter()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        times_b.append(t1 - t0)
        peak_mem_b = max(peak_mem_b, peak)

    results["BS4 lxml"] = {
        "median_ms": median(times_b) * 1000,
        "p95_ms": sorted(times_b)[int(len(times_b) * 0.95)] * 1000,
        "peak_mb": peak_mem_b / 1024 / 1024,
    }

    # Variant (c): Scrapling
    if Selector is not None:
        times_c = []
        peak_mem_c = 0
        for _ in range(num_iterations):
            tracemalloc.start()
            t0 = time.perf_counter()
            extract_with_scrapling(html)
            t1 = time.perf_counter()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            times_c.append(t1 - t0)
            peak_mem_c = max(peak_mem_c, peak)

        results["Scrapling Selector"] = {
            "median_ms": median(times_c) * 1000,
            "p95_ms": sorted(times_c)[int(len(times_c) * 0.95)] * 1000,
            "peak_mb": peak_mem_c / 1024 / 1024,
        }
    else:
        results["Scrapling Selector"] = {"error": "Scrapling not installed"}

    return results


def main():
    print("=" * 120)
    print("OLX Parser Benchmark: BeautifulSoup4 vs Scrapling")
    print("=" * 120)
    print(f"Iterations per fixture: {NUM_ITERATIONS}")
    print(f"Fixtures directory: {FIXTURES_DIR}")
    print()

    all_results = {}
    for fixture in FIXTURES:
        fixture_path = FIXTURES_DIR / fixture
        if not fixture_path.exists():
            print(f"SKIP {fixture} (not found)")
            continue

        print(f"Benchmarking {fixture}...", end=" ", flush=True)
        try:
            results = benchmark_fixture(fixture)
            all_results[fixture] = results
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
            all_results[fixture] = {"error": str(e)}

    # Print summary table
    print("\n" + "=" * 130)
    print("BENCHMARK RESULTS SUMMARY")
    print("=" * 130)
    print()

    for fixture in FIXTURES:
        fixture_path = FIXTURES_DIR / fixture
        if not fixture_path.exists():
            continue

        print(f"\nFixture: {fixture}")
        print("-" * 130)
        print(f"{'Variant':<30} {'Median (ms)':<20} {'P95 (ms)':<20} {'Peak Mem (MB)':<20}")
        print("-" * 130)

        if fixture in all_results and "error" not in all_results[fixture]:
            results = all_results[fixture]
            for variant in ["BS4 html.parser", "BS4 lxml", "Scrapling Selector"]:
                if variant in results:
                    r = results[variant]
                    if "error" in r:
                        print(f"{variant:<30} ERROR: {r['error']}")
                    else:
                        print(
                            f"{variant:<30} {r['median_ms']:<20.6f} {r['p95_ms']:<20.6f} {r['peak_mb']:<20.4f}"
                        )
        else:
            print(f"  ERROR: {all_results.get(fixture, {}).get('error', 'Unknown error')}")

    print("\n" + "=" * 130)
    print("END OF BENCHMARK")
    print("=" * 130)


if __name__ == "__main__":
    main()
