from app.sources.types import ScrapeContext
from app.scrapers.icarros import scrape_icarros

ctx = ScrapeContext(source="icarros", force_browser=True, browser_fallback_enabled=True)
url = "https://www.icarros.com.br/comprar/sao-jose-do-rio-preto-sp/audi/a6"
items = scrape_icarros(url, ctx)
print("items:", len(items))
for it in items[:3]:
    print(it.get("title"), it.get("price"), it.get("thumbnail_url"), it.get("url"))
