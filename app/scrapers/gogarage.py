from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.services.browser_fetcher import fetch_html_browser


def _parse_brl_price_to_decimal(text: str) -> Optional[Decimal]:
    if not text:
        return None
    t = text.strip().replace('R$', '').strip()
    t = t.replace('.', '').replace(',', '.')
    try:
        return Decimal(t)
    except Exception:
        return None


def scrape_gogarage(search_url: str) -> list[dict]:
    res = fetch_html_browser(search_url)
    html = res.html
    soup = BeautifulSoup(html, 'html.parser')

    items: list[dict] = []
    seen: set[str] = set()

    # Heuristic: GoGarage tends to have clean listing URLs under gogarage.com.br
    for a in soup.find_all('a', href=True):
        href = a.get('href') or ''
        if 'gogarage.com.br' in href:
            full = href
        else:
            full = urljoin('https://gogarage.com.br', href)

        if 'gogarage.com.br' not in full:
            continue
        if '/carro/' not in full and '/veiculo/' not in full and '/anuncio/' not in full:
            continue

        m = re.search(r'(\d{6,})', full)
        external_id = m.group(1) if m else full
        if external_id in seen:
            continue
        seen.add(external_id)

        title = (a.get('aria-label') or a.get_text(' ', strip=True) or '').strip()
        if not title or len(title) < 6:
            continue

        price_text = None
        parent = a.parent
        if parent:
            txt = parent.get_text(' ', strip=True)
            pm = re.search(r'R\$\s*[0-9\.]+(\,[0-9]{2})?', txt)
            if pm:
                price_text = pm.group(0)
        price = _parse_brl_price_to_decimal(price_text) if price_text else None

        items.append({
            'source': 'gogarage',
            'external_id': str(external_id),
            'title': title,
            'url': full,
            'thumbnail_url': None,
            'price': price,
            'currency': 'BRL',
            'location': None,
        })

        if len(items) >= 60:
            break

    return items
