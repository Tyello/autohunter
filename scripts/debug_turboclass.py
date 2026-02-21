#!/usr/bin/env python3
import argparse
import re
import sys
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

DETAIL_RE = re.compile(r"^/anuncio/detalhe/")

def fetch(url: str, timeout: int = 25) -> requests.Response:
    r = requests.get(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
        timeout=timeout,
        allow_redirects=True,
    )
    return r

def extract_detail_links(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if DETAIL_RE.match(href):
            links.append(base.rstrip("/") + href)
    # de-dup mantendo ordem
    seen = set()
    out = []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def anti_bot_hints(html: str) -> list[str]:
    h = html.lower()
    hints = []
    for key in ["cloudflare", "captcha", "access denied", "incapsula", "sucuri", "ddos", "forbidden"]:
        if key in h:
            hints.append(key)
    # “página vazia JS”
    if ("<script" in h and "/anuncio/detalhe/" not in h):
        hints.append("muito script e zero links de detalhe (pode ser render JS)")
    return hints

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="termo (ex: 'civic si')")
    ap.add_argument("--pages", type=int, default=3, help="quantas páginas testar")
    ap.add_argument("--base", default="https://turboclass.com.br", help="base url")
    ap.add_argument("--find", default="", help="string pra procurar (ex: 'tc-b9ylgi')")
    ap.add_argument("--list-only", action="store_true", help="testa listagem sem query")
    args = ap.parse_args()

    base = args.base.rstrip("/")

    targets = []
    if args.list_only:
        for pg in range(1, args.pages + 1):
            targets.append(f"{base}/anuncio-lista.php?o=&pg={pg}")
    else:
        q = quote_plus(args.query.strip())
        for pg in range(1, args.pages + 1):
            targets.append(f"{base}/anuncio-lista.php?o=&pg={pg}&q={q}")

    total_links = 0
    for url in targets:
        print(f"\n== FETCH {url}")
        r = fetch(url)
        print(f"status={r.status_code} final_url={r.url}")
        ct = r.headers.get("content-type", "")
        print(f"content-type={ct} bytes={len(r.content)}")

        html = r.text or ""
        hints = anti_bot_hints(html)
        if hints:
            print(f"hints={hints}")

        links = extract_detail_links(html, base)
        total_links += len(links)
        print(f"detail_links={len(links)}")
        for u in links[:10]:
            print(" -", u)

        if args.find:
            hit = [u for u in links if args.find in u]
            if hit:
                print(f"FOUND '{args.find}' on this page:")
                for u in hit:
                    print(" *", u)

    print(f"\nDONE total_detail_links={total_links}")
    if total_links == 0:
        print("=> Se isso aqui é 0 mas o site no browser mostra cards, então é render JS/anti-bot.")
        print("=> Se list-only >0 mas com query =0, então a busca q= não indexa seu termo (ex: 'si').")
    return 0

if __name__ == "__main__":
    sys.exit(main())