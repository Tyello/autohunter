from __future__ import annotations

def sanitize_for_telegram(text: str) -> str:
    """
    Remove caracteres Unicode inválidos (surrogates) que quebram urllib/urlencode no envio ao Telegram.
    """
    if not text:
        return text

    # Remove qualquer surrogate isolado (U+D800–U+DFFF)
    # Jeito mais simples e seguro: encode ignora surrogates e outros inválidos
    return text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
