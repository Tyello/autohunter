#!/usr/bin/env python3
"""
Prova/refuta o ponto 5 registrado em docs/spikes/scrapling-parser-spike.md:
a fixture usada no benchmark original (search_rsc_price_nodes.html, ~15 KB,
2 anuncios) pode nao ser representativa do tamanho real de uma pagina de
busca OLX em producao (que lista ~40 anuncios por pagina).

Estrategia: repete o <script>self.__next_f.push(...)</script> real da
fixture N vezes, trocando o sufixo dos listId em cada copia (pra nao colidir
com o dedupe de _extract_items_from_next_data), simulando paginas com
2, 20, 40 e 80 anuncios reais. Roda o mesmo benchmark de 3 variantes
(BS4 html.parser / BS4 lxml / scrapling.Selector) em cada tamanho e imprime
como a razao de velocidade muda com a escala.

Nao inventa HTML novo: cada copia contem os MESMOS dois anuncios reais
(Honda Fit 2021/2005) ja commitados em tests/fixtures/olx/search_rsc_price_nodes.html.
"""

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

from bench_scrapling_parser import (
    extract_next_data_json,
    extract_rsc_json_chunks,
)

FIXTURE_PATH = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "olx" / "search_rsc_price_nodes.html"
)
NUM_ITERATIONS = 30
REPEAT_COUNTS = [1, 10, 20, 40]  # ~2, ~20, ~40, ~80 anuncios simulados


def build_scaled_html(base_html: str, repeats: int) -> str:
    """Duplica o <script> RSC real `repeats` vezes, com listId unicos por copia."""
    m = re.search(r"<script>self\.__next_f\.push\(.*?\)</script>", base_html, re.DOTALL)
    if not m:
        raise ValueError("script RSC nao encontrado na fixture base")
    script_block = m.group(0)

    copies = []
    for i in range(repeats):
        # Sufixo unico nos dois listId reais (1503037487 / 1512208902) pra
        # cada copia gerar um external_id diferente e nao ser deduplicada.
        block = script_block.replace("1503037487", f"1503037487{i:03d}")
        block = block.replace("1512208902", f"1512208902{i:03d}")
        copies.append(block)

    return base_html.replace(script_block, "\n".join(copies))


def extract_with_bs4(html: str, parser: str) -> dict:
    soup = BeautifulSoup(html, parser)
    next_data = extract_next_data_json(html)
    rsc_chunks = extract_rsc_json_chunks(html)
    cards = soup.select('a[data-testid="adcard-link"]')
    return {"next_data": bool(next_data), "rsc_chunks": len(rsc_chunks), "cards": len(cards)}


def extract_with_scrapling(html: str) -> dict:
    if Selector is None:
        return {"error": "not installed"}
    selector = Selector(html)
    next_data_str = selector.css("script#__NEXT_DATA__::text").get()
    rsc_chunks = extract_rsc_json_chunks(html)
    cards = selector.css('a[data-testid="adcard-link"]')
    return {
        "next_data": bool(next_data_str),
        "rsc_chunks": len(rsc_chunks),
        "cards": len(cards.getall()) if cards else 0,
    }


def time_variant(fn, html: str, iterations: int) -> dict:
    times = []
    peak_mem = 0
    for _ in range(iterations):
        tracemalloc.start()
        t0 = time.perf_counter()
        fn(html)
        t1 = time.perf_counter()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times.append(t1 - t0)
        peak_mem = max(peak_mem, peak)
    return {
        "median_ms": median(times) * 1000,
        "p95_ms": sorted(times)[int(len(times) * 0.95)] * 1000,
        "peak_mb": peak_mem / 1024 / 1024,
    }


def main():
    base_html = FIXTURE_PATH.read_text(encoding="utf-8")

    print("=" * 110)
    print("Benchmark escalado: efeito do tamanho real da pagina na razao scrapling/BS4")
    print("=" * 110)
    print(f"Iterations per size/variant: {NUM_ITERATIONS}")
    print()

    header = f"{'Anuncios':<10} {'Tamanho (KB)':<14} {'Variante':<22} {'Mediana (ms)':<16} {'Razao vs (a)':<14}"
    print(header)
    print("-" * len(header))

    for repeats in REPEAT_COUNTS:
        html = build_scaled_html(base_html, repeats)
        n_ads = repeats * 2
        size_kb = len(html.encode("utf-8")) / 1024

        r_a = time_variant(lambda h: extract_with_bs4(h, "html.parser"), html, NUM_ITERATIONS)
        r_b = time_variant(lambda h: extract_with_bs4(h, "lxml"), html, NUM_ITERATIONS)
        r_c = (
            time_variant(extract_with_scrapling, html, NUM_ITERATIONS)
            if Selector is not None
            else {"median_ms": float("nan")}
        )

        base_ms = r_a["median_ms"]
        print(f"{n_ads:<10} {size_kb:<14.1f} {'(a) BS4 html.parser':<22} {r_a['median_ms']:<16.4f} {'1.00x':<14}")
        print(f"{'':<10} {'':<14} {'(b) BS4 lxml':<22} {r_b['median_ms']:<16.4f} {base_ms / r_b['median_ms']:<14.2f}")
        print(
            f"{'':<10} {'':<14} {'(c) Scrapling Selector':<22} {r_c['median_ms']:<16.4f} "
            f"{base_ms / r_c['median_ms'] if r_c['median_ms'] else float('nan'):<14.2f}"
        )
        print()


if __name__ == "__main__":
    main()
