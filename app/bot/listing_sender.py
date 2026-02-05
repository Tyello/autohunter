from __future__ import annotations

from io import BytesIO

from telegram import Update

from app.bot.media import download_image_bytes

TELEGRAM_CAPTION_MAX = 1024
TELEGRAM_TEXT_MAX = 4096


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _split(text: str, limit: int) -> tuple[str, str]:
    if not text:
        return "", ""
    if len(text) <= limit:
        return text, ""
    return text[:limit], text[limit:]


async def send_listing_message(
    update: Update,
    *,
    text: str,
    thumbnail_url: str | None = None,
    referer_url: str | None = None,
    reply_markup=None,
    disable_web_page_preview: bool = True,
    prefer_photo_url: bool = False,
    allow_local_image_download: bool = True,
) -> None:
    """Send listing text with optional image and robust fallback.

    Order:
    1) If `prefer_photo_url=True`, try Telegram URL fetch first.
    2) Optionally try local download + upload bytes.
    3) Fallback to plain text.

    If the message is larger than Telegram caption limit, it sends the remainder
    as a second text message.
    """
    full_text = text or ""
    caption, remainder = _split(full_text, TELEGRAM_CAPTION_MAX)
    caption = _truncate(caption, TELEGRAM_CAPTION_MAX)

    sent_photo = False

    if thumbnail_url and prefer_photo_url:
        try:
            await update.message.reply_photo(
                photo=thumbnail_url,
                caption=caption,
                reply_markup=reply_markup,
            )
            sent_photo = True
        except Exception:
            sent_photo = False

    if thumbnail_url and not sent_photo and allow_local_image_download:
        img = download_image_bytes(thumbnail_url, referer=referer_url)
        if img:
            img_bytes, ctype = img
            bio = BytesIO(img_bytes)
            ext = ".jpg" if ("jpeg" in (ctype or "")) else (
                ".png" if ("png" in (ctype or "")) else (
                    ".webp" if ("webp" in (ctype or "")) else ".img"
                )
            )
            bio.name = f"thumb{ext}"
            try:
                await update.message.reply_photo(
                    photo=bio,
                    caption=caption,
                    reply_markup=reply_markup,
                )
                sent_photo = True
            except Exception:
                sent_photo = False

    if sent_photo:
        if remainder.strip():
            await update.message.reply_text(
                _truncate(remainder.strip(), TELEGRAM_TEXT_MAX),
                disable_web_page_preview=disable_web_page_preview,
            )
        return

    await update.message.reply_text(
        _truncate(full_text, TELEGRAM_TEXT_MAX),
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )
