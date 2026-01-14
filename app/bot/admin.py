from app.core.settings import settings


def is_admin(chat_id: int) -> bool:
    raw = settings.autohunter_admins or ""
    allowed = {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}
    return chat_id in allowed
