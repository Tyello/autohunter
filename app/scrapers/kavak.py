from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import urljoin

from lxml import html as lxml_html

from app.scrapers.parsing import parse_brl_price
from app.scrapers.contract import finalize_listings
from app.scrapers.utils import clean_text
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


_KAVAK_BASE = "https://www.kavak.com"


def _external_id_from_url(url: str) -> str:
    # Kavak URLs are often stable slugs, ex: /br/venda/honda-civic-20_ex_cvt-sedan-2018
    m = re.search(r"/br/venda/([^/?#]+)", url)
    if m:
        return m.group(1)
    # fallback: last path segment
    return (url.split("?")[0].rstrip("/").split("/")[-1] or url)


_RSC_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
_RSC_KM_RE = re.compile(r"([\d.]+)\s*km", re.IGNORECASE)


def _extract_rsc_cars(html_text: str) -> dict[str, dict]:
    """O HTML da Kavak (Next.js App Router, streaming) ja embute o payload
    RSC com a lista completa de carros (price/km/ano/local) em scripts
    `self.__next_f.push(...)`, mesmo apos renderizacao via browser (ver
    docs/spikes/scraping-efetividade-audit.md secao 4). Retorna um dict
    `url -> {price, km, year, location}` para enriquecer o que o parser de
    DOM ja extraiu, sem requisicao extra."""
    out: dict[str, dict] = {}

    for raw in _RSC_CHUNK_RE.findall(html_text):
        if "cars" not in raw:
            continue
        try:
            unescaped = json.loads('"' + raw + '"')
        except Exception:
            continue

        idx = unescaped.find('"cars":[')
        if idx == -1:
            continue
        start = idx + len('"cars":')

        depth = 0
        end = None
        for i in range(start, len(unescaped)):
            ch = unescaped[i]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            continue

        try:
            cars = json.loads(unescaped[start:end])
        except Exception:
            continue

        for car in cars:
            if not isinstance(car, dict):
                continue
            url = car.get("url")
            if not url:
                continue

            analytics = car.get("analytics") if isinstance(car.get("analytics"), dict) else {}

            km = None
            m = _RSC_KM_RE.search(car.get("subtitle") or "")
            if m:
                try:
                    km = int(m.group(1).replace(".", ""))
                except Exception:
                    km = None

            price = None
            car_price = analytics.get("car_price")
            if car_price is not None:
                try:
                    price = int(str(car_price))
                except Exception:
                    price = None

            out[url] = {
                "price": price,
                "km": km,
                "year": analytics.get("car_year"),
                "location": analytics.get("car_location"),
            }

    return out


def scrape_kavak(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Kavak scraper (Playwright-first).

    Kavak é JS-heavy. A estratégia aqui é:
    - renderizar a página de resultados com Playwright
    - para cada card, extrair title/price/km/location/thumb do *card container*
      (não só do texto do <a>, que costuma vir "colado" e incompleto).
    """
    res = fetch_html_browser(search_url, ctx=ctx, timeout_ms=60000, wait_until="domcontentloaded")
    html_text = res.html

    doc = lxml_html.fromstring(html_text)
    doc.make_links_absolute(res.final_url or search_url)

    PRICE_RE = re.compile(r"R\$\s*[\d\.]+(?:,\d{2})?", re.IGNORECASE)
    KM_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d{1,7})\s*km\b", re.IGNORECASE)

    def find_card(a):
        cur = a
        for _ in range(6):
            if cur is None:
                break
            tag = getattr(cur, "tag", "") or ""
            if tag.lower() in ("article", "li", "section", "div"):
                # card típico: tem um h2/h3 OU tem algum preço/km dentro
                txt = clean_text(cur.text_content() or "")
                if (cur.xpath(".//h1|.//h2|.//h3") or "r$" in txt.lower() or KM_RE.search(txt)):
                    return cur
            cur = cur.getparent()
        return a

    def pick_best_image(el) -> Optional[str]:
        candidates: list[str] = []

        for img in el.xpath(".//img"):
            for attr in ("data-src", "data-lazy-src", "data-original", "data-srcset", "srcset", "src"):
                v = img.get(attr)
                if not v:
                    continue
                if "srcset" in attr:
                    # Kavak às vezes põe srcset com múltiplos tamanhos
                    first = v.split(",")[0].strip().split(" ")[0]
                    candidates.append(first)
                else:
                    candidates.append(v)

        for ss in el.xpath(".//picture//source[@srcset]/@srcset"):
            first = ss.split(",")[0].strip().split(" ")[0]
            candidates.append(first)

        def score(u: str) -> int:
            s = 0
            ul = (u or "").lower()
            if not ul:
                return -10
            if ul.startswith("data:"):
                return -50
            if any(k in ul for k in ("logo", "icon", "sprite")):
                s -= 8
            if ul.endswith(".svg") or "svg" in ul:
                s -= 8
            if re.search(r"\.(jpe?g|png|webp)\b", ul):
                s += 6
            if "kavak" in ul:
                s += 2
            if any(k in ul for k in ("photo", "image", "img", "car")):
                s += 1
            mw = re.search(r"[?&]w=(\d+)", ul)
            if mw:
                try:
                    s += min(int(mw.group(1)) // 200, 4)
                except Exception:
                    pass
            return s

        best = None
        best_s = -10**9
        for raw in candidates:
            u = raw
            if u.startswith("//"):
                u = "https:" + u
            if u.startswith("/"):
                u = urljoin(res.final_url or search_url, u)
            sc = score(u)
            if sc > best_s:
                best_s = sc
                best = u
        return best

    def extract_title(card, fallback_text: str) -> Optional[str]:
        # Prefere h1/h2/h3 dentro do card
        for xp in (".//h1", ".//h2", ".//h3"):
            nodes = card.xpath(xp)
            if nodes:
                t = clean_text(nodes[0].text_content())
                if t and len(t) >= 4:
                    return t
        # fallback: texto do link, mas limpo
        t = clean_text(fallback_text)
        # remove preço/km colados
        t = PRICE_RE.sub("", t)
        t = KM_RE.sub("", t)
        t = re.sub(r"\bReservado\b", "", t, flags=re.IGNORECASE)
        t = clean_text(t)
        return t or None

    def extract_location(card, card_text: str) -> Optional[str]:
        # tenta encontrar um nó "pequeno" de localização
        for xp in (
            ".//*[contains(translate(@data-testid,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'location')]",

            ".//*[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'location')]",

            ".//*[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'cidade')]",

        ):
            nodes = card.xpath(xp)
            for n in nodes[:3]:
                t = clean_text(n.text_content())
                # evita pegar o próprio título
                if t and len(t) <= 40 and "r$" not in t.lower() and not KM_RE.search(t):
                    return t

        # heurística: último "token" capitalizado (ex: 'São Paulo')
        tail = clean_text(card_text)
        # corta em 'Automático'/'Manual' e pega o que sobrou
        tail = re.sub(r"^.*\b(autom[aá]tico|manual)\b", "", tail, flags=re.IGNORECASE).strip()
        tail = re.sub(r"\bReservado\b", "", tail, flags=re.IGNORECASE).strip()
        if tail and len(tail) <= 40:
            return tail
        return None

    by_url: dict[str, dict] = {}

    for a in doc.xpath("//a[contains(@href, '/br/venda/')]"):
        href = a.get("href") or ""
        if not href:
            continue
        url = urljoin(res.final_url or search_url, href)
        if "/br/venda/" not in url:
            continue

        card = find_card(a)
        card_text = clean_text(card.text_content() or "")
        a_text = clean_text(a.text_content() or "")

        external_id = _external_id_from_url(url)

        reserved = "reservado" in card_text.lower()

        price = None
        m = PRICE_RE.search(card_text)
        if m:
            price = parse_brl_price(m.group(0))

        thumb = pick_best_image(card)

        title = extract_title(card, a_text)
        if title and reserved and not title.lower().startswith("reservado") and "reservado" not in title.lower():
            title = f"⚠️ RESERVADO — {title}"

        loc = extract_location(card, card_text)

        cur = by_url.get(url) or {
            "source": "kavak",
            "external_id": external_id,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": None,
        }

        if cur.get("title") is None and title:
            cur["title"] = title
        if cur.get("price") is None and price is not None:
            cur["price"] = price
        if cur.get("thumbnail_url") is None and thumb:
            cur["thumbnail_url"] = thumb
        if cur.get("location") is None and loc:
            cur["location"] = loc

        by_url[url] = cur

    # Fallback: regex extraction (último recurso)
    if not by_url:
        for m in re.finditer(r"https?://www\.kavak\.com/br/venda/[^\"\']+", html_text):
            url = m.group(0).split('"')[0].split("'")[0]
            by_url[url] = {
                "source": "kavak",
                "external_id": _external_id_from_url(url),
                "url": url,
                "title": None,
                "price": None,
                "thumbnail_url": None,
                "location": None,
            }

    # Enrich price/km/year/location from the RSC payload already embedded in
    # the page HTML (no extra request).
    rsc_cars = _extract_rsc_cars(html_text)
    for cur in by_url.values():
        car = rsc_cars.get(cur["url"])
        if not car:
            continue
        if cur.get("price") is None and car.get("price") is not None:
            cur["price"] = car["price"]
        if cur.get("location") is None and car.get("location"):
            cur["location"] = car["location"]
        if car.get("km") is not None:
            cur["km"] = car["km"]
        if car.get("year") is not None:
            cur["year"] = car["year"]

    return finalize_listings("kavak", list(by_url.values()))
