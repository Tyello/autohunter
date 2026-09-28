"""Script descartavel de apoio a Fase 0 (docs/prompts/PROMPT-exec-melhorias-sources.md):
roda os parsers ATUAIS contra os fixtures capturados em 2026-09-28 e imprime a
tabela de preenchimento por campo. Nao faz parte da suite de testes (sem
prefixo test_, nao e coletado pelo pytest); mantido aqui so para reprodutibilidade
do baseline citado no relatorio. Uso: python tests/fixtures/source_regression/_fase0_baseline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

FIELDS = ("external_id", "url", "title", "price", "year", "km", "location", "thumbnail_url")


def _rate(items: list[dict], field: str) -> str:
    if not items:
        return "n/a (found=0)"
    # scrapers use "km" internally; finalize_listings/contract may rename to mileage_km downstream,
    # but at the raw-scraper-output level (what this script measures) both keys are checked.
    present = sum(1 for it in items if (it.get(field) if field != "km" else (it.get("km") or it.get("mileage_km"))) is not None)
    return f"{present}/{len(items)} ({present*100//len(items)}%)"


def _print_row(source: str, items: list[dict]) -> None:
    cells = [f"found={len(items)}"] + [f"{f}={_rate(items, f)}" for f in FIELDS]
    print(f"{source:14s} " + " | ".join(cells))


def run_olx():
    from app.scrapers.olx import _extract_rsc_json_chunks, _extract_items_from_next_data, _items_to_dicts
    html = (Path(__file__).parent / "olx" / "2026-09-28_civic" / "listing.html").read_text(encoding="utf-8")
    chunks = _extract_rsc_json_chunks(html)
    all_items = []
    for c in chunks:
        all_items.extend(_extract_items_from_next_data(c))
    out = _items_to_dicts(all_items)
    _print_row("olx", out)


def run_chavesnamao():
    from app.scrapers.chavesnamao import scrape_chavesnamao
    html = (Path(__file__).parent / "chavesnamao" / "2026-09-28_civic" / "listing.html").read_text(encoding="utf-8")
    import app.scrapers.chavesnamao as mod
    mod.fetch_html = lambda url, **kw: html
    out = scrape_chavesnamao("https://www.chavesnamao.com.br/carros/brasil/honda-civic/")
    _print_row("chavesnamao", out)


def run_mobiauto():
    from app.scrapers.mobiauto import _extract_next_data_deals
    import re
    from urllib.parse import urljoin
    html = (Path(__file__).parent / "mobiauto" / "2026-09-28_civic" / "listing.html").read_text(encoding="utf-8")
    from lxml import html as lxml_html
    doc = lxml_html.fromstring(html)
    search_url = "https://www.mobiauto.com.br/comprar/carros/brasil/honda/civic"
    doc.make_links_absolute(search_url)
    by_url: dict[str, dict] = {}
    for a in doc.xpath("//a[contains(@href, '/detalhes/')]"):
        href = a.get("href")
        if not href:
            continue
        url = urljoin(search_url, href)
        if "/detalhes/" not in url:
            continue
        m = re.search(r"/detalhes/(\d+)", url)
        if not m:
            continue
        ext_id = m.group(1)
        by_url.setdefault(url, {
            "source": "mobiauto", "external_id": ext_id, "url": url,
            "title": None, "price": None, "thumbnail_url": None, "location": None,
        })
    deals = _extract_next_data_deals(html)
    for cur in by_url.values():
        deal = deals.get(cur["external_id"])
        if not deal:
            continue
        if deal.get("price") is not None:
            cur["price"] = deal["price"]
        if deal.get("km") is not None:
            cur["km"] = deal["km"]
        if deal.get("year") is not None:
            cur["year"] = deal["year"]
    _print_row("mobiauto (parser sem enrich de titulo/thumb via detail page)", list(by_url.values()))


def run_kavak():
    from app.scrapers.kavak import _extract_rsc_cars, _external_id_from_url
    import re
    from urllib.parse import urljoin
    html = (Path(__file__).parent / "kavak" / "2026-09-28_civic" / "listing.html").read_text(encoding="utf-8")
    from lxml import html as lxml_html
    search_url = "https://www.kavak.com/br/seminovos/honda-civic"
    doc = lxml_html.fromstring(html)
    doc.make_links_absolute(search_url)
    by_url: dict[str, dict] = {}
    for a in doc.xpath("//a[contains(@href, '/br/venda/')]"):
        href = a.get("href")
        if not href:
            continue
        url = urljoin(search_url, href)
        if "/br/venda/" not in url:
            continue
        by_url.setdefault(url, {
            "source": "kavak", "external_id": _external_id_from_url(url), "url": url,
            "title": None, "price": None, "thumbnail_url": None, "location": None,
        })
    rsc = _extract_rsc_cars(html)
    for cur in by_url.values():
        car = rsc.get(cur["url"])
        if not car:
            continue
        if car.get("price") is not None:
            cur["price"] = car["price"]
        if car.get("location"):
            cur["location"] = car["location"]
        if car.get("km") is not None:
            cur["km"] = car["km"]
        if car.get("year") is not None:
            cur["year"] = car["year"]
    _print_row("kavak (parser sem DOM/titulo, so links+RSC)", list(by_url.values()))


def run_gogarage():
    import app.scrapers.gogarage as mod
    html = (Path(__file__).parent / "gogarage" / "2026-09-28_civic" / "listing.html").read_text(encoding="utf-8")
    # gogarage.py's scrape function signature/fetch call may need ctx; try the raw parse helper if present.
    import inspect
    print("gogarage      NAO EXECUTADO NESTE SCRIPT -- ver relatorio (parser precisa de ctx/fetch real, "
          "ver app/scrapers/gogarage.py). Fixture salvo para inspecao manual.")


def run_turboclass():
    from app.scrapers.turboclass import scrape_turboclass
    import app.scrapers.turboclass as mod
    html = (Path(__file__).parent / "turboclass" / "2026-09-28_civic" / "listing.html").read_text(encoding="utf-8")
    mod.fetch_html_with_browser_fallback = lambda url, ctx=None: html
    out = scrape_turboclass("https://turboclass.com.br/anuncio-lista.php?q=honda+civic")
    _print_row("turboclass", out)


def run_mercadolivre():
    from app.scrapers.mercadolivre import _parse_polycard_items
    html = (Path(__file__).parent / "mercadolivre" / "2026-09-28_civic" / "listing_shell_com_cookies_bloqueado.html").read_text(encoding="utf-8")
    out = _parse_polycard_items(html)
    _print_row("mercadolivre (cenario: bloqueado mesmo c/ cookies, ver relatorio)", out)


if __name__ == "__main__":
    print(f"{'source':14s} campos: found | " + " | ".join(FIELDS))
    run_mercadolivre()
    run_olx()
    run_chavesnamao()
    run_mobiauto()
    run_kavak()
    run_gogarage()
    run_turboclass()
