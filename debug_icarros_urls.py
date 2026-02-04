import asyncio
import re
from playwright.async_api import async_playwright

URLS = [
    "https://www.icarros.com.br/comprar/rio-de-janeiro-rj/audi/a6/2020/d56149836",
]

def pick_best_srcset(srcset: str) -> str | None:
    # ex: "https://... 320w, https://... 640w, https://... 1024w"
    best = None
    best_w = -1
    for part in srcset.split(","):
        part = part.strip()
        m = re.match(r"^(?P<url>\S+)\s+(?P<w>\d+)w$", part)
        if not m:
            continue
        w = int(m.group("w"))
        if w > best_w:
            best_w = w
            best = m.group("url")
    return best

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # headful pra ver o redirect
        page = await browser.new_page()
        for url in URLS:
            print("\n=== DEBUG ICARROS ===")
            print("requested_url:", url)

            resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)  # dá tempo do SPA mexer no URL

            print("final_url    :", page.url)
            print("status       :", resp.status if resp else None)

            # og:title / og:image
            og_title = await page.locator("meta[property='og:title']").get_attribute("content")
            og_image = await page.locator("meta[property='og:image']").get_attribute("content")
            print("og:title     :", og_title)
            print("og:image     :", og_image)

            # tenta achar um srcset grande
            srcset = await page.locator("img[srcset]").first.get_attribute("srcset")
            if srcset:
                best = pick_best_srcset(srcset)
                print("srcset_best  :", best)

            # se cair em /a6#rfae, tenta achar um dID novo no HTML
            html = await page.content()
            ids = re.findall(r"/comprar/[^\"']+/(\d{4})/(d\d+)", html)
            if ids:
                print("found_detail_ids:", list(dict.fromkeys(ids))[:10])

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
