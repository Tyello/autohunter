from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo


def parse_money_br(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = re.sub(r"[^\d,.-]", "", value)
    if not cleaned:
        return None
    normalized = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except Exception:
        return None


def parse_int_br(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def parse_year_from_title(title: str | None) -> int | None:
    if not title:
        return None
    m = re.search(r"\b(19\d{2}|20\d{2})\b", title)
    return int(m.group(1)) if m else None


def normalize_title(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" -_:\t\n\r")
    return cleaned or None


def parse_mileage(value: str | None) -> int | None:
    if not value:
        return None
    hit = re.search(r"(\d[\d\.,\s]{1,15})\s*(?:km|quil[oô]metros?)", value, flags=re.I)
    return parse_int_br(hit.group(1) if hit else value)


def absolute_url(base_url: str, url: str | None) -> str | None:
    if not url:
        return None
    return urljoin(base_url, url)


def external_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    slug = path.split("/")[-1] if path else ""
    nums = re.findall(r"\d{3,}", path)
    if nums:
        return nums[-1]
    if slug:
        return slug.lower()
    return None


def extract_state_from_location(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"\b([A-Z]{2})\b", text.upper())
    return m.group(1) if m else None


def normalize_item_type(category_text: str | None) -> str:
    text = (category_text or "").lower()
    if re.search(r"\b(im[oó]vel(?:es)?|apartamento|casa|terreno|sala comercial)\b", text):
        return "real_estate"
    if "moto" in text:
        return "motorcycle"
    if re.search(r"\b(escavadeira|trator(?:es)?|retroescavadeira|p[áa]\s+carregadeira|motoniveladora)\b", text):
        return "heavy"
    if re.search(r"\b(caminh[aã]o(?:es)?|ônibus|onibus|van|utilit[áa]rio)\b", text):
        return "truck"
    if "autom" in text or "car" in text or "auto" in text or "veíc" in text or "veic" in text:
        return "car"
    return "other"


def normalize_status(text: str | None) -> str:
    val = (text or "").lower()
    if "aberto para lance" in val or "aberto" in val:
        return "open"
    if "compre agora" in val:
        return "buy_now"
    if "leil" in val or "auction" in val:
        return "auction"
    if "vend" in val or "sold" in val or "encerr" in val:
        return "sold"
    return "unknown"


def parse_datetime_br(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = " ".join(value.strip().split())

    try:
        iso_candidate = cleaned.replace("Z", "+00:00")
        iso_dt = datetime.fromisoformat(iso_candidate)
        if iso_dt.tzinfo is None:
            iso_dt = iso_dt.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
        return iso_dt.astimezone(ZoneInfo("UTC"))
    except ValueError:
        pass

    cleaned = re.sub(r"\s+às\s+", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*-\s*", " ", cleaned)
    cleaned = re.sub(r"([0-9])h([0-9]{2})", r"\1:\2", cleaned, flags=re.I)

    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%d/%m/%y %H:%M", "%d/%m/%y"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            parsed = parsed.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
            return parsed.astimezone(ZoneInfo("UTC"))
        except ValueError:
            continue
    return None
