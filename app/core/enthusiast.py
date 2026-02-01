from __future__ import annotations

import re
from dataclasses import dataclass


_RE_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")

# Auction / salvage signals (Portuguese-centric).
_RE_AUCTION = re.compile(
    r"\b(leil[aã]o|leiloeir|lote\b|hasta\b|alien[aã]c[aã]o|judicial|extrajudicial)\b",
    re.IGNORECASE,
)
_RE_AUCTION_BRANDS = re.compile(
    r"\b(sodr[eé]\s*santoro|freitas\s*leil[oõ]es|copart|iaa|b3\s*leil[oõ]es)\b",
    re.IGNORECASE,
)

_RE_SALVAGE = re.compile(
    r"\b(sucata|batid[oa]|sinistr|recuperad[oa]|perda\s*total|pt\b|salvage)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ListingSignals:
    year: int | None
    is_auction: bool
    is_salvage: bool


def extract_year(text: str | None) -> int | None:
    t = text or ""
    m = _RE_YEAR.search(t)
    if not m:
        return None
    try:
        y = int(m.group(1))
    except Exception:
        return None
    if 1900 <= y <= 2100:
        return y
    return None


def detect_signals(title: str | None, location: str | None = None) -> ListingSignals:
    blob = " ".join([title or "", location or ""]).strip()
    year = extract_year(blob)
    is_auction = bool(_RE_AUCTION.search(blob) or _RE_AUCTION_BRANDS.search(blob))
    is_salvage = bool(_RE_SALVAGE.search(blob))
    return ListingSignals(year=year, is_auction=is_auction, is_salvage=is_salvage)


def compute_enthusiast_score(title: str | None, location: str | None = None) -> int:
    """Offline 'enthusiast' score.

    Goal:
    - Give a wide, meaningful spread (not just 50-58).
    - Favor older (>=1985) enthusiast cars: sports, JDM, hot hatches.
    - Penalize auctions/salvage heavily.

    This is intentionally heuristic and cheap (Raspberry Pi friendly).
    """

    t = (title or "").lower()
    loc = (location or "").lower()
    blob = f"{t} {loc}".strip()

    sig = detect_signals(title, location)

    score = 50

    # Year preference (enthusiasts + older platform compatibility)
    if sig.year:
        y = sig.year
        if 1985 <= y <= 1994:
            score += 15
        elif 1995 <= y <= 2004:
            score += 12
        elif 2005 <= y <= 2012:
            score += 6
        elif 2013 <= y <= 2019:
            score += 2
        elif y >= 2020:
            score -= 3
        else:
            # pre-1985: can be awesome, but tends to be niche/parts headache
            score += 5

    # Core enthusiast signals
    plus = [
        (r"\b(turbo|tbi|supercharger|kompressor)\b", 12),
        (r"\b(manual|mec[aâ]nic[oa])\b", 10),
        (r"\b(hatch|hatchback|hot\s*hatch)\b", 6),
        (r"\b(jdm|importad[oa])\b", 10),

        # Trims / badges
        (r"\b(gti|type\s*r|ctr)\b", 18),
        (r"\b(si|vti|vts|vts)\b", 12),
        (r"\b(gts|rs|r\b|cupra)\b", 10),
        (r"\b(wrx|sti)\b", 18),
        (r"\b(mps|st\b|rs\b)\b", 10),

        # Engines / codes (common enthusiast shorthand)
        (r"\b(vtec|k20|b16|b18)\b", 12),
        (r"\b(sr20|rb26|2jz|4g63|13b)\b", 14),

        # Mods (not always good, but usually 'enthusiast')
        (r"\b(remap|stage\s*[123]|downpipe|intake|coilover|swap)\b", 8),
        (r"\b(track\s*day|pista)\b", 6),
    ]

    minus = [
        (r"\b(1\.0|tr[êe]s\s*cilindros|3\s*cilindros)\b", -6),
        (r"\b(suv|crossover)\b", -6),
        (r"\b(cvt)\b", -4),
        (r"\b(frota|locadora|uber)\b", -8),
        (r"\b(financiamento|parcelas)\b", -2),
    ]

    for pat, w in plus:
        if re.search(pat, blob):
            score += w
    for pat, w in minus:
        if re.search(pat, blob):
            score += w

    # Heavy penalties
    if sig.is_auction:
        score -= 30
    if sig.is_salvage:
        score -= 40

    return max(0, min(100, int(score)))
