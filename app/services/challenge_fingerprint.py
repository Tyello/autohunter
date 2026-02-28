from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ChallengeFingerprint:
    provider: str
    title: str
    final_url: str
    snippet: str


_PROVIDER_PATTERNS = [
    ("cloudflare", re.compile(r"(cloudflare|cf-ray|attention required|checking your browser)", re.I)),
    ("perimeterx", re.compile(r"(perimeterx|px-captcha|\b_px\b|_px|px\.js)", re.I)),
    ("datadome", re.compile(r"(datadome|captcha-delivery|dd_captcha|ddos)", re.I)),
    ("hcaptcha", re.compile(r"(hcaptcha)", re.I)),
    ("recaptcha", re.compile(r"(recaptcha)", re.I)),
    ("cookie_consent", re.compile(r"(consent|cookie|cookies|lgpd)", re.I)),
]

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _strip_html_to_text(html: str) -> str:
    # Remove scripts/styles and tags; keep a readable text snippet.
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    html = re.sub(r"\s+", " ", html).strip()
    return html


def fingerprint_challenge(html: str, final_url: str = "", max_snippet: int = 600) -> Optional[ChallengeFingerprint]:
    """
    Returns a short fingerprint if the HTML looks like an anti-bot challenge / consent page, else None.
    """
    if not html:
        return None

    provider = "unknown"
    for name, rx in _PROVIDER_PATTERNS:
        if rx.search(html):
            provider = name
            break

    m = _TITLE_RE.search(html)
    title = (m.group(1).strip() if m else "")[:140]

    text = _strip_html_to_text(html)
    snippet = text[:max_snippet]

    # Heuristic signals
    lower = text.lower()
    signals = [
        "captcha",
        "checking your browser",
        "acesso negado",
        "verificando",
        "robô",
        "robot",
        "temporarily unavailable",
    ]
    if provider != "unknown" or any(s in lower for s in signals):
        return ChallengeFingerprint(provider=provider, title=title, final_url=final_url or "", snippet=snippet)

    return None


# Backwards-compatible alias: some callers import fingerprint_from_html(...)
def fingerprint_from_html(html: str, final_url: str = "", max_snippet: int = 600) -> Optional[ChallengeFingerprint]:
    return fingerprint_challenge(html, final_url=final_url, max_snippet=max_snippet)
