from urllib.parse import quote_plus


def ml_url(query: str) -> str:
    q = quote_plus(query.strip())
    return f"https://lista.mercadolivre.com.br/{q}"


def olx_url(query: str) -> str:
    q = quote_plus(query.strip())
    return f"https://www.olx.com.br/brasil?q={q}"
