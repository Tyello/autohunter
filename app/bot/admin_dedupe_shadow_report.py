from __future__ import annotations

from typing import Any

DEFAULT_SHADOW_HOURS = 24
DEFAULT_SHADOW_LIMIT = 20


def _cap_hours(hours: int) -> int:
    return max(1, min(168, int(hours or DEFAULT_SHADOW_HOURS)))


def _cap_limit(limit: int) -> int:
    return max(1, min(50, int(limit or DEFAULT_SHADOW_LIMIT)))


def parse_dedupe_shadow_args(args: list[str]) -> tuple[int, int]:
    hours = DEFAULT_SHADOW_HOURS
    limit = DEFAULT_SHADOW_LIMIT
    if len(args) >= 2:
        try:
            hours = int(args[1])
        except Exception:
            hours = DEFAULT_SHADOW_HOURS
    if len(args) >= 3:
        try:
            limit = int(args[2])
        except Exception:
            limit = DEFAULT_SHADOW_LIMIT
    return _cap_hours(hours), _cap_limit(limit)


def _short(v: Any, n: int = 18) -> str:
    s = str(v or "-").strip() or "-"
    return s if len(s) <= n else s[: n - 1] + "…"


def render_cross_source_dedupe_shadow_report(report: dict) -> str:
    flags = report.get("flags") or {}
    events = report.get("events") or {}
    window = int(report.get("window_hours") or 24)
    lines = [
        "🔎 Cross-source dedupe — shadow report",
        "",
        f"Janela: {window}h",
        "",
        "Flags:",
        f"- enabled: {'true' if bool(flags.get('enabled', False)) else 'false'}",
        f"- shadow mode: {'true' if bool(flags.get('shadow_mode', True)) else 'false'}",
        f"- window: {int(flags.get('window_days', 30) or 30)}d",
        "",
        "Eventos:",
        f"- would suppress: {int(events.get('shadow_hit', 0) or 0)}",
        f"- suppressed live: {int(events.get('live_suppressed', 0) or 0)}",
        f"- errors: {int(events.get('evaluation_error', 0) or 0)}",
        "",
    ]
    total = int(events.get("shadow_hit", 0) or 0) + int(events.get("live_suppressed", 0) or 0) + int(events.get("evaluation_error", 0) or 0)
    if total == 0:
        lines.append("Nenhum evento de shadow/live encontrado na janela.")
        return "\n".join(lines)

    lines.append("Sources:")
    for row in (report.get("top_source_pairs") or [])[:5]:
        lines.append(f"- {row.get('current_source') or '-'} → {row.get('matched_source') or '-'}: {int(row.get('count') or 0)}")
    lines.extend(["", "Fingerprints mais frequentes:"])
    for row in (report.get("top_fingerprints") or [])[:5]:
        lines.append(f"- {_short(row.get('fingerprint'), 12)}: {int(row.get('count') or 0)}")

    lines.extend(["", "Exemplos:"])
    for i, ex in enumerate((report.get("examples") or [])[:10], start=1):
        lines.extend(
            [
                f"[{i}] {ex.get('current_source') or '-'} → {ex.get('matched_source') or '-'}",
                f"fp={_short(ex.get('fingerprint'), 18)}",
                f"current={_short(ex.get('current_listing_id'), 18)}",
                f"matched={_short(ex.get('matched_listing_id'), 18)}",
            ]
        )
    lines.extend(["", "Próximo passo:", "Revise amostras antes de ativar live mode."])
    return "\n".join(lines)
