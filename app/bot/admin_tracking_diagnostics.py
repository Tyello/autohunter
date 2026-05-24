from __future__ import annotations

from datetime import datetime
from typing import Any

MAX_EXAMPLES = 5


def _fmt_dt(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


def _truncate(items: list[dict], limit: int = MAX_EXAMPLES) -> list[dict]:
    return (items or [])[:limit]


def render_tracking_diagnostics(payload: dict) -> str:
    tracked = (payload or {}).get("tracked") or {}
    notif = (payload or {}).get("price_drop_notifications") or {}
    job = (payload or {}).get("last_tracking_job") or {}
    examples = (payload or {}).get("examples") or {}
    window = int((payload or {}).get("window_hours") or 24)

    lines = [
        "📡 Tracking de preço — diagnóstico",
        "",
        f"Janela: {window}h",
        "",
        "Rastreados:",
        f"- total: {int(tracked.get('total') or 0)}",
        f"- alertas ativos: {int(tracked.get('price_drop_alert_enabled') or 0)}",
        f"- active: {int(tracked.get('active') or 0)}",
        f"- inactive: {int(tracked.get('inactive') or 0)}",
        f"- orphan: {int(tracked.get('orphan') or 0)}",
        f"- unknown: {int(tracked.get('unknown') or 0)}",
        "",
        "Preço:",
        f"- sem último preço observado: {int(tracked.get('last_observed_price_null') or 0)}",
        f"- sem last_seen_at: {int(tracked.get('last_seen_at_null') or 0)}",
        f"- com mudança registrada: {int(tracked.get('price_change_recorded') or 0)}",
        f"- quedas: {int(tracked.get('dropped') or 0)}",
        f"- altas: {int(tracked.get('increased') or 0)}",
        f"- inalterado/nulo: {int(tracked.get('unchanged_or_null') or 0)}",
        "",
        "Price drop:",
        f"- queued: {int(notif.get('queued') or 0)}",
        f"- processing: {int(notif.get('processing') or 0)}",
        f"- sent: {int(notif.get('sent') or 0)}",
        f"- failed: {int(notif.get('failed') or 0)}",
        f"- último alerta: {_fmt_dt(notif.get('latest_created_at'))}",
        "",
        "Job:",
        f"- última execução: {_fmt_dt(job.get('created_at'))}",
        f"- status: {(job.get('level') or 'desconhecido')}",
        "",
        "Atenção:",
        f"- {int(tracked.get('orphan') or 0)} órfãos",
        f"- {int(tracked.get('last_observed_price_null') or 0)} sem preço observado",
        "- observabilidade apenas (não aplica correção automática).",
    ]

    for title, key in (("Exemplos órfãos", "orphans"), ("Exemplos quedas", "recent_drops"), ("Alertas pendentes", "pending_alerts")):
        sample = _truncate(examples.get(key) or [])
        if not sample:
            continue
        lines.extend(["", f"{title}: "])
        for row in sample:
            lines.append(f"- {str(row)[:180]}")

    return "\n".join(lines).strip()


def parse_tracking_window_hours(args: list[str]) -> int:
    if not args:
        return 24
    raw = (args[-1] or "").strip()
    try:
        value = int(raw)
    except Exception:
        return 24
    return max(1, min(168, value))
