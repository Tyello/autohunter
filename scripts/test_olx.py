from app.scrapers.olx import build_olx_search_url, scrape_olx

if __name__ == "__main__":
    url = build_olx_search_url("civic si", page=1)
    items = scrape_olx(url)
    print("URL:", url)
    print("QTD:", len(items))
    for i, it in enumerate(items[:5], 1):
        print(f"{i}. {it.external_id} | {it.price} | {it.title} | {it.url}")
