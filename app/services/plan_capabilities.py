from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanCapabilities:
    plan_code: str
    max_active_wishlists: int
    max_tracked_per_wishlist: int
    tracking_auto_alerts: bool
    daily_notification_limit: int
    premium: bool


_FREE = PlanCapabilities("free", 2, 1, False, 10, False)
_PREMIUM = PlanCapabilities("premium", 10, 3, True, 50, True)


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
            "Você já está rastreando 1 anúncio nesta wishlist, que é o limite do plano Free.\n\n"
            "No Premium você pode rastrear até 3 anúncios por wishlist e receber alertas automáticos de queda de preço.\n\n"
            f"{premium_upgrade_cta()}"
        )
    return f"Limite atingido ({max_tracked}/{max_tracked}). Remova um slot com /wishlist_track_remove <n> <slot>."


def automation_unavailable_message() -> str:
    return (
        "Alertas automáticos de tracking não estão disponíveis no plano Free.\n"
        "No Premium você recebe alertas automáticos de queda de preço.\n\n"
        f"{premium_upgrade_cta()}"
    )
