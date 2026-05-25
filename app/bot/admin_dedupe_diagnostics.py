from __future__ import annotations

from typing import Any

DEFAULT_COLLISIONS_LIMIT = 10
MAX_COLLISIONS_LIMIT = 20
MAX_EXAMPLES_PER_FINGERPRINT = 3
MAX_TITLE_LEN = 56


def _short(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"
    return text[: limit - 1].rstrip() + "…"


def _fmt_price(price: Any) -> str:
    if price is None:
        return "-"
    try:
        value = float(price)
    except Exception:
        return "-"
    formatted = f"{value:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _fmt_mileage(mileage_km: Any) -> str:
    if mileage_km is None:
        return "-"
    try:
        value = int(mileage_km)
    except Exception:
        return "-"
    formatted = f"{value:,}".replace(",", ".")
    return f"{formatted} km"


def render_cross_source_dedupe_collisions(collisions: list[dict], *, dedupe_flags: dict[str, Any] | None = None) -> str:
    flags = dedupe_flags or {}
    suppression_enabled = bool(flags.get("enabled", False))
    shadow_mode = bool(flags.get("shadow_mode", True))
    window_days = int(flags.get("window_days", 30) or 30)
    mode = "shadow" if shadow_mode else "live"
    header = [
        "🔎 Cross-source dedupe — diagnóstico",
        "",
    ]

    if not collisions:
        return "\n".join(
            header
            + [
                "Nenhuma colisão cross-source encontrada agora.",
                "",
                "Status:",
                "- fingerprint: ativo",
                f"- suppression enabled: {'true' if suppression_enabled else 'false'}",
                f"- shadow mode: {'true' if shadow_mode else 'false'}",
                f"- window: {window_days}d",
                f"- mode: {mode}",
            ]
        )

    lines = header + [
        "Cross-source dedupe",
        "- fingerprint: ativo",
        f"- suppression enabled: {'true' if suppression_enabled else 'false'}",
        f"- shadow mode: {'true' if shadow_mode else 'false'}",
        f"- window: {window_days}d",
        f"- mode: {mode}",
        "",
    ]

    for idx, collision in enumerate(collisions, start=1):
        fp = _short(collision.get("fingerprint") or "-", 24)
        sources = collision.get("sources") or []
        source_list = ", ".join(str(s) for s in sources if s) or "-"
        listing_count = int(collision.get("listing_count") or 0)
        source_count = int(collision.get("source_count") or 0)

        lines.extend(
            [
                f"[{idx}] {fp}",
                f"Sources ({source_count}): {source_list}",
                f"Listings: {listing_count}",
            ]
        )

        examples = collision.get("examples") or []
        for ex in examples[:MAX_EXAMPLES_PER_FINGERPRINT]:
            source = str(ex.get("source") or "-").strip() or "-"
            source_label = source[:1].upper() + source[1:]
            title = _short(ex.get("title") or "Sem título", MAX_TITLE_LEN)
            lines.append(
                f"- {source_label}: {title} | {_fmt_price(ex.get('price'))} | {_fmt_mileage(ex.get('mileage_km'))}"
            )
        lines.append("")

    return "\n".join(lines).strip()


def parse_dedupe_collisions_limit(args: list[str]) -> int:
    if len(args) < 2:
        return DEFAULT_COLLISIONS_LIMIT
    raw = (args[1] or "").strip()
    try:
        value = int(raw)
    except Exception:
        return DEFAULT_COLLISIONS_LIMIT
    return max(1, min(MAX_COLLISIONS_LIMIT, value))
