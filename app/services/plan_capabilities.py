from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanCapabilities:
    plan_code: str
    max_active_wishlists: int
    max_tracked_total: int
    max_tracked_slots_per_wishlist: int
    tracking_auto_alerts: bool
    daily_notifications_per_wishlist: int
    premium: bool
    launch_price_brl: float | None = None
    future_price_brl: float | None = None


_FREE = PlanCapabilities("free", 2, 1, 3, False, 5, False, None, None)
_PREMIUM = PlanCapabilities("premium", 10, 5, 3, True, 15, True, 5.99, 9.99)


def normalize_plan_code(plan_code: str | None) -> str:
    code = str(plan_code or "free").strip().lower()
    if code in {"premium", "pro", "ultra", "paid"}:
        return "premium"
    if code in {"free", "basic"}:
        return "free"
    return "free"


def get_plan_capabilities(plan_code: str | None) -> PlanCapabilities:
    normalized = normalize_plan_code(plan_code)
    return _PREMIUM if normalized == "premium" else _FREE


def premium_upgrade_cta() -> str:
    return "Use /upgrade para ver os benefícios."


def wishlist_limit_message(max_w: int) -> str:
    return (
        "Você atingiu o limite do plano Free.\n\n"
        f"No Free você pode ter até {max_w} wishlists ativas.\n"
        "No Premium você libera até 10 wishlists, mais rastreados e alertas automáticos.\n\n"
        f"{premium_upgrade_cta()}"
    )


def tracking_limit_message(max_tracked: int) -> str:
    if max_tracked <= 1:
        return (
            "Você já está rastreando 1 anúncio, que é o limite do plano Free.\n\n"
            "No Premium você pode rastrear até 5 anúncios no total e receber alertas automáticos de queda de preço.\n\n"
            "Use /upgrade para assinar por R$ 5,99/mês."
        )
    return (
        f"Limite atingido: você já está rastreando {max_tracked} anúncios no total.\n\n"
        "Remova algum rastreado com /wishlist_track_remove <n> <slot> ou revise em /wishlist_track_list."
    )


def tracking_slots_full_message(max_slots: int) -> str:
    return (
        f"Esta wishlist já tem {max_slots} anúncios rastreados, que é o limite por wishlist.\n\n"
        "Use outra wishlist ou remova um slot com /wishlist_track_remove <n> <slot>."
    )


def automation_unavailable_message() -> str:
    return (
        "Alertas automáticos de tracking não estão disponíveis no plano Free.\n"
        "No Premium você pode rastrear até 5 anúncios no total e recebe alertas automáticos de queda de preço.\n\n"
        "Use /upgrade para assinar por R$ 5,99/mês."
    )
