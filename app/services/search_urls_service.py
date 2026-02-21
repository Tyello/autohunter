from urllib.parse import quote_plus

import re
import unicodedata


# Chaves na Mão tem padrões de URL por modelo (SSR) bem melhores do que `?q=`.
# Mantemos a lógica de resolução no scraper para reutilizar no bot e no scheduler.
from app.scrapers.chavesnamao import build_chavesnamao_search_url

def _slugify(text: str) -> str:
    s = (text or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "-")
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


# Remove termos de ano/range do texto para construir URLs canônicas por marca/modelo.
# Ex.: 'audi a6 entre 2014 e 2020' -> 'audi a6'
# Isso NÃO afeta matching (só URL builder).
_RE_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")

def _strip_year_phrases(text: str) -> str:
    t = (text or '').strip()
    if not t:
        return ''
    low = t.lower()
    # padrões comuns em pt-BR
    low = re.sub(r"\bentre\s+(19\d{2}|20\d{2})\s+e\s+(19\d{2}|20\d{2})\b", ' ', low)
    low = re.sub(r"\bde\s+(19\d{2}|20\d{2})\s+a\s+(19\d{2}|20\d{2})\b", ' ', low)
    low = re.sub(r"\b(19\d{2}|20\d{2})\s*[-/]\s*(19\d{2}|20\d{2})\b", ' ', low)
    low = re.sub(r"\bat[eé]\s+(19\d{2}|20\d{2})\b", ' ', low)
    # remove anos soltos
    low = _RE_YEAR.sub(' ', low)
    low = re.sub(r"\s+", ' ', low).strip()
    return low


# Minimal brand/model inference to build friendlier URLs when user doesn't type a brand.
# You can extend this list freely.
_MODEL_TO_BRAND = {
    "civic": "honda",
    "corolla": "toyota",
    "fit": "honda",
    "hr-v": "honda",
    "honda-hrv": "honda",
    "city": "honda",
    "cr-v": "honda",
    "golf": "volkswagen",
    "jetta": "volkswagen",
    "virtus": "volkswagen",
    "gol": "volkswagen",
    "polo": "volkswagen",
    "up": "volkswagen",
    "uno": "fiat",
    "palio": "fiat",
    "strada": "fiat",
    "onix": "chevrolet",
    "prisma": "chevrolet",
    "cruze": "chevrolet",
    "tracker": "chevrolet",
    "hb20": "hyundai",
    "creta": "hyundai",
    "sandero": "renault",
    "duster": "renault",
    "kicks": "nissan",
    "sentra": "nissan",
    "versa": "nissan",
    "corcel": "ford",
    "ka": "ford",
    "fiesta": "ford",
    "focus": "ford",
    "ecosport": "ford",

    # JDM / entusiastas (recall alto em buscas curtas)
    "lancer": "mitsubishi",
    "impreza": "subaru",
    "wrx": "subaru",
    "brz": "subaru",
    "supra": "toyota",
}


_BRANDS = set([
    "honda","toyota","volkswagen","vw","fiat","chevrolet","gm","hyundai","renault","nissan","ford",
    "bmw","mercedes","audi","jeep","peugeot","citroen","kia","mitsubishi","subaru","suzuki",
])


def _infer_brand_model(query: str) -> tuple[str | None, str | None]:
    q = _slugify(query)
    if not q:
        return None, None
    parts = q.split("-")
    if not parts:
        return None, None

    first = parts[0]
    if first in ("vw",):
        first = "volkswagen"
    if first in ("gm",):
        first = "chevrolet"

    # If the query begins with a known brand, treat the rest as model.
    if first in _BRANDS and len(parts) >= 2:
        return first, "-".join(parts[1:])

    # Else: infer brand by the first token as model
    model = parts[0]
    brand = _MODEL_TO_BRAND.get(model)
    if brand:
        # Keep 2 tokens max for model (e.g. civic-si -> civic)
        return brand, model

    # fallback: no brand; use the whole slug as "model-ish"
    return None, q


def ml_url(query: str) -> str:
    """Mercado Livre URL builder.

    Importante: buscas de veículos (carros/caminhonetes) canonicalizam em:
      https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/<slug>

    O host `carro.mercadolivre.com.br/<slug>` costuma redirecionar/canonicalizar
    para o host `lista.*` e isso quebrava o guardrail do scraper (found=0).
    """

    slug = _slugify(query)
    if not slug:
        slug = "carro"
    return f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{slug}"


def olx_url(query: str) -> str:
    q = quote_plus((query or "").strip())
    return f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q={q}"


def webmotors_url(query: str) -> str:
    """Webmotors URL builder.

    - Mantém compatibilidade com `...&search=`
    - Quando possível, tenta construir filtros canônicos (`marca1`/`modelo1`) a partir do texto.
      Isso reduz ruído e melhora recall/precisão.
    """

    raw = (query or "").strip()
    q = quote_plus(raw)

    raw2 = _strip_year_phrases(raw)
    brand, model = _infer_brand_model(raw2 or raw)
    if brand and model:
        def _brand_display(b: str) -> str:
            b = (b or "").strip().lower()
            if b in ("vw", "volkswagen"):
                return "Volkswagen"
            if b in ("gm", "chevrolet"):
                return "Chevrolet"
            if b == "bmw":
                return "BMW"
            if b == "kia":
                return "Kia"
            return b.capitalize()

        def _model_display(m: str) -> str:
            m = (m or "").strip().lower()
            # alguns modelos usam hífen e siglas
            if m in ("hr-v", "cr-v", "mx-5", "gt-r"):
                return m.upper()
            if m in ("brz", "wrx", "sti", "gti"):
                return m.upper()
            # padrão: título (Virtus, Civic, Golf)
            return m.replace("-", " ").title()

        b_disp = quote_plus(_brand_display(brand))
        m_disp = quote_plus(_model_display(model))

        # tenta preservar “resto” do prompt como search (ex.: "virtus gts")
        rest = ""
        slug = _slugify(raw2 or raw)
        parts = [p for p in slug.split("-") if p]
        if parts:
            # se o usuário não começou pela marca, a inferência normalmente pega o primeiro token como modelo
            if parts[0] == model:
                rest = " ".join(parts[1:]).strip()

        url = f"https://www.webmotors.com.br/carros/estoque?tipoveiculo=carros&marca1={b_disp}&modelo1={m_disp}"
        if rest:
            url += f"&search={quote_plus(rest)}"
        return url

    return f"https://www.webmotors.com.br/carros/estoque?tipoveiculo=carros&search={q}"


def gogarage_url(query: str) -> str:
    # GoGarage é JS-heavy e historicamente alterna rotas.
    # O mais estável tem sido o host com www + index.php (evita 404 em /?q=).
    raw = (query or "").strip()
    # GoGarage search é bem literal: se colocarmos "entre 2014 e 2020" ou anos,
    # o site frequentemente devolve resultados errados/irrelevantes.
    raw2 = _strip_year_phrases(raw)
    # remove anos soltos (ex: "x3 2012")
    raw2 = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", raw2 or "")
    raw2 = re.sub(r"\s+", " ", raw2).strip()

    q = quote_plus(raw2 or raw)
    return f"https://www.gogarage.com.br/index.php?q={q}"


def chavesnamao_url(query: str) -> str:
    return build_chavesnamao_search_url(query)


def kavak_url(query: str) -> str:
    # Kavak pages are usually JS-heavy; still, a stable "seminovos" URL works well with Playwright.
    slug = _slugify(query)
    if not slug:
        slug = "carros"
    return f"https://www.kavak.com/br/seminovos/{slug}"


def mobiauto_url(query: str) -> str:
    """Mobiauto URL builder.

    Mobiauto tem URLs canônicas por marca/modelo:
      https://www.mobiauto.com.br/comprar/carros/brasil/<marca>/<modelo>
    """

    raw = (query or '').strip()

    raw2 = _strip_year_phrases(raw)

    # Inferência padrão (quando usuário informa marca/modelo)
    brand, model = _infer_brand_model(raw2 or raw)
    if brand and model:
        return f"https://www.mobiauto.com.br/comprar/carros/brasil/{brand}/{model}"

    # Fallback: broad listing (o filtro por termos acontece no pós-processamento)
    return 'https://www.mobiauto.com.br/comprar/carros/brasil'


def icarros_url(query: str) -> str:
    # iCarros commonly uses /comprar/usados/<brand>/<model>
    brand, model = _infer_brand_model(query)
    if brand and model:
        return f"https://www.icarros.com.br/comprar/usados/{brand}/{model}"
    # Fallback: generic search landing page (browser will be needed anyway)
    q = quote_plus((query or "").strip())
    return f"https://www.icarros.com.br/busca?anunciante=concessionaria&produto=carro&palavra-chave={q}"


def facebook_marketplace_url(query: str) -> str:
    q = quote_plus((query or "").strip())
    # Location will be resolved by Facebook itself; Playwright will return final_url after redirects.
    return f"https://www.facebook.com/marketplace/search/?query={q}"


def turboclass_url(query: str) -> str:
    """TurboClass URL builder.

    TurboClass expõe uma listagem SSR em `anuncio-lista.php`.
    A navegação do site usa os parâmetros:
      - `q`: busca livre
      - `pg`: paginação
      - `o`: ordenação

    Mesmo se o `q` variar em efetividade entre releases do site, o AutoHunter
    ainda filtra/ranqueia por título no pós-processamento.
    """
    q = quote_plus((query or "").strip())
    return f"https://turboclass.com.br/anuncio-lista.php?o=&pg=1&q={q}"
