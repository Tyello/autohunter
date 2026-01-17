from urllib.parse import quote_plus


# Chaves na Mão tem padrões de URL por modelo (SSR) bem melhores do que `?q=`.
# Mantemos a lógica de resolução no scraper para reutilizar no bot e no scheduler.
from app.scrapers.chavesnamao import build_chavesnamao_search_url


def ml_url(query: str) -> str:
    q = quote_plus(query.strip())
    return f"https://lista.mercadolivre.com.br/{q}"


def olx_url(query: str) -> str:
    q = quote_plus(query.strip())
    return f"https://www.olx.com.br/brasil?q={q}"


def webmotors_url(query: str) -> str:
    # Webmotors é SPA e a busca real acontece via endpoints internos.
    # Para MVP, guardamos o URL de estoque (ainda útil para debug / futura implementação).
    q = quote_plus(query.strip())
    return f"https://www.webmotors.com.br/carros/estoque?tipoveiculo=carros&search={q}"


def gogarage_url(query: str) -> str:
    # GoGarage também carrega via JS. Mantemos um URL estável para a página de busca.
    q = quote_plus(query.strip())
    return f"https://gogarage.com.br/buscar?q={q}"


def chavesnamao_url(query: str) -> str:
    return build_chavesnamao_search_url(query)
