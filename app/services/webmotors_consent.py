from __future__ import annotations

from typing import Sequence


DEFAULT_CONSENT_TEXTS: Sequence[str] = (
    "aceitar",
    "concordo",
    "entendi",
    "permitir",
    "ok",
)


async def try_click_consent(page, texts: Sequence[str] = DEFAULT_CONSENT_TEXTS) -> bool:
    """Best-effort: click cookie/consent buttons by visible text. Returns True if something was clicked."""
    clicked = False
    for t in texts:
        for selector in (
            f"button:has-text('{t}')",
            f"a:has-text('{t}')",
            f"input[type='button'][value*='{t}' i]",
            f"input[type='submit'][value*='{t}' i]",
        ):
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.click(timeout=1500)
                    clicked = True
                    await page.wait_for_timeout(800)
            except Exception:
                pass
    return clicked
