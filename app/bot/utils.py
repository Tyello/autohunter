from __future__ import annotations

from typing import Iterable

from telegram import Message, Update


def get_message(update: Update) -> Message | None:
    return update.effective_message


async def reply_text(update: Update, text: str, **kwargs) -> bool:
    message = get_message(update)
    if not message:
        return False
    await message.reply_text(text, **kwargs)
    return True


def normalize_args(args: Iterable[str] | None) -> list[str]:
    return [str(a).strip() for a in (args or []) if str(a).strip()]


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw.isdigit():
        return None
    return int(raw)
