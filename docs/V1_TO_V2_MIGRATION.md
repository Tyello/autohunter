# V1 → V2: Gaps e Melhorias a Implementar
> ⚠️ Status real de runtime deve ser conferido em `docs/SOURCES_ARCHITECTURE.md` (código atual é a fonte de verdade).

> O que cada scraper v1 tem de battle-tested que a v2 ainda não herdou.
> Documento de referência para migração incremental via modo `dual`.

---

## Como usar este documento

Para cada source, o fluxo é:
1. Ativar `impl=dual` no `source_configs.extra` da source
2. Implementar os itens listados na v2
3. Observar o relatório de comparação do dual por 48–72h
4. Quando paridade ≥ 95% de itens encontrados → flipar para `impl=v2`

```sql
-- Ativar dual para uma source
UPDATE source_configs
SET extra = extra || '{"impl": "dual"}'::jsonb
WHERE source = 'mercadolivre';

-- Flipar para v2 quando validado
UPDATE source_configs
SET extra = extra || '{"impl": "v2"}'::jsonb
WHERE source = 'mercadolivre';
```

---

## Gap 1 — `unified_fetch`: ausência de `curl_cffi` (afeta ML e OLX)

**Onde está na v1:** `app/scrapers/mercadolivre.py::_fetch_html_ml` e `app/scrapers/olx.py`

**O que faz:** `curl_cffi` é uma biblioteca que faz requisições HTTP impersonando o fingerprint TLS de um browser real (Chrome 120). Muitos sites detectam `requests`/`httpx` pelo handshake TLS e bloqueiam antes de verificar headers. O `curl_cffi` passa por essa camada sem precisar de Playwright.

**Estratégia v1 do ML (3 passos):**
```
1. HTTP normal (fetch_html com cookies do storage_state)
2. curl_cffi com impersonate="chrome120" + headers completos + proxy opcional
3. Playwright (último recurso, só se Playwright habilitado)
```

**O que a v2 faz hoje:** `unified_fetch` vai direto de HTTP para Playwright. Não tem o passo intermediário do `curl_cffi`.

**O que implementar no `fetcher.py`:**

```python
# scraper_base/fetcher.py — adicionar estratégia intermediária

def unified_fetch(url: str, ctx: ScrapeContext, source: str) -> FetchResult:
    # ... lógica existente ...

    # Entre HTTP e browser: tentar curl_cffi se disponível
    try:
        from curl_cffi import requests as cf_requests
        _CURL_CFFI_AVAILABLE = True
    except ImportError:
        _CURL_CFFI_AVAILABLE = False

    if not ctx.force_browser and fetch_mode == 'http':
        # 1. HTTP normal
        try:
            content = fetch_html(url, ctx=ctx)
            return FetchResult(content=content, method="http", ...)
        except FetchBlocked:
            pass

        # 2. curl_cffi (novo — entre HTTP e browser)
        if _CURL_CFFI_AVAILABLE:
            try:
                impersonate = getattr(ctx, 'curl_cffi_impersonate', None) or "chrome120"
                r = cf_requests.get(
                    url,
                    headers=_build_browser_headers(url),
                    impersonate=impersonate,
                    timeout=25,
                    proxies={"http": ctx.proxy_server, "https": ctx.proxy_server} if ctx.proxy_server else None,
                )
                if r.status_code == 200 and r.text:
                    return FetchResult(content=r.text, method="curl_cffi", ...)
            except Exception:
                pass

        # 3. Playwright (já existe)
        if ctx.browser_fallback_enabled:
            ...
```

**Adicionar ao `ScrapeContext` (ou `source_configs.extra`):**
```python
curl_cffi_impersonate: str = "chrome120"  # chrome99, chrome110, chrome120, firefox
curl_cffi_enabled: bool = True
```

---

## Gap 2 — ML: extração via POLYCARD + merge com BeautifulSoup

**Onde está na v1:** `app/scrapers/mercadolivre.py::_parse_polycard_items` + merge final

**O que faz:** POLYCARD é o layout atual do ML (substituiu o layout antigo de cards `ui-search-layout__item`). A v1 faz **dois parsers em paralelo** e merge os resultados:

- Parser 1: regex no HTML bruto buscando `"polycard":{..."id":"MLB..."` → mais rápido e mais confiável para ID/URL/preço
- Parser 2: BeautifulSoup nos `<li class="ui-search-layout__item">` → mais robusto para thumbnail e campos visuais

O merge completa campos faltantes de um parser com o outro. Se o POLYCARD não tem thumbnail, pega do BeautifulSoup. Se o BeautifulSoup não tem preço, pega do POLYCARD.

**O que a v2 faz hoje:** `extract_raw_data` usa só BeautifulSoup em seletores CSS. Não extrai POLYCARD.

**O que implementar no `sources/mercadolivre.py`:**

```python
def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
    # Parser 1: POLYCARD via regex (layout atual)
    poly_items = self._parse_polycard(raw_content)

    # Parser 2: BeautifulSoup fallback (layout legado)
    soup_items = self._parse_soup(raw_content)

    # Merge: POLYCARD como base, BeautifulSoup completa gaps
    return self._merge_results(poly_items, soup_items)

def _parse_polycard(self, html: str) -> List[Dict]:
    """Extrai MLB id, URL, preço e título do bloco POLYCARD via regex."""
    items = []
    pattern = re.compile(
        r'"polycard"\s*:\s*\{.*?"metadata"\s*:\s*\{.*?"id"\s*:\s*"(MLB\d+)".*?"url"\s*:\s*"(.*?)"',
        re.DOTALL
    )
    for m in pattern.finditer(html):
        external_id = m.group(1)
        raw_url = _unescape_ml(m.group(2))
        # ... extrair title, price, thumbnail do bloco components
        items.append({...})
    return items
```

---

## Gap 3 — ML: filtro anti-peças (`_vehicle_relevance_score`)

**Onde está na v1:** `app/scrapers/mercadolivre.py::_vehicle_relevance_score`, `_PART_KEYWORDS`, `_VEHICLE_POSITIVE_TERMS`

**O que faz:** O ML retorna peças e acessórios misturados com carros nas buscas genéricas. Sem esse filtro, termos como "civic" retornam "Cabo de vela Honda Civic" junto com os carros. O score analisa o card e penaliza palavras-chave de peças (`pistão`, `filtro`, `correia`, `pastilha`, etc.) e premia sinais de veículo completo (ano 4 dígitos, km, câmbio, carroceria).

**Conjunto de keywords v1 (copiar integralmente):**
```python
_PART_KEYWORDS = {
    "cabo", "embreagem", "pistao", "pistão", "anel", "biela", "correia", "correia dentada",
    "filtro", "vela", "bobina", "amortecedor", "pastilha", "disco", "radiador",
    "farol", "lanterna", "retrovisor", "parachoque", "para-choque", "sensor",
    "bomba", "rolamento", "mangueira", "tampa", "retentor", "escapamento",
    "ponteira", "alternador", "arranque", "motor de arranque", "compressor",
    "condensador", "evaporador", "mola", "molas", "suspensao", "suspensão",
}

_VEHICLE_POSITIVE_TERMS = {
    "km", "quilometr", "ano", "manual", "automático", "automatico", "câmbio", "cambio",
    "gasolina", "etanol", "flex", "diesel", "híbrido", "hibrido", "elétrico", "eletrico",
    "hatch", "sedan", "cupê", "cupe", "suv", "picape", "pickup", "caminhonete", "perua", "wagon",
}

def _vehicle_relevance_score(text: str, title: str = "") -> int:
    blob = (text or "").lower()
    ttitle = (title or "").lower()
    score = 0
    if re.search(r"\b(19\d{2}|20\d{2})\b", blob):
        score += 2
    if re.search(r"\b\d{1,3}(?:[\.,]\d{3})+\s*km\b|\b\d+\s*km\b", blob):
        score += 1
    if any(term in blob for term in _VEHICLE_POSITIVE_TERMS):
        score += 1
    if any(k in ttitle for k in _PART_KEYWORDS):
        score -= 2
    if re.search(r"\b(kit|jg\.?|jogo)\b", ttitle):
        score -= 1
    return score
```

**Threshold:** descartar item se `score < 2`.

**O que implementar:** adicionar como pós-filtro em `parse_listing` do `MercadoLivreScraper`:
```python
def parse_listing(self, raw_data: dict) -> dict | None:
    # ... extração normal ...
    blob = f"{title or ''} {str(raw_data)}"
    if _vehicle_relevance_score(blob, title or "") < 2:
        return None  # descarta peça/acessório
    return listing
```

---

## Gap 4 — ML: URLs de tracking patrocinado

**Onde está na v1:** `app/scrapers/mercadolivre.py::_is_tracking_url`, `_extract_tracking_destination`, `_normalize_ml_url`, `_canonical_url_from_external_id`

**O que faz:** O ML mistura anúncios orgânicos com patrocinados. Os patrocinados têm URLs de tracking no formato `click*.mercadolivre.com.br/brand_ads/clicks?url=<destino_encodado>`. Sem resolução, o external_id extraído da URL de tracking é inválido (hash ao invés de MLB-XXXXXX), causando dedupe falso e URL inútil no alerta.

**Cadeia de resolução v1:**
1. Detecta se é URL de tracking (`click*` no host ou `/brand_ads/clicks` no path)
2. Extrai o parâmetro `url=` (múltiplas camadas de encoding)
3. Se não conseguir extrair, tenta achar o MLB id no HTML do card via regex
4. Se tiver MLB id mas não URL, reconstrói URL canônica: `https://carro.mercadolivre.com.br/MLB-{id}-_JM`

**O que implementar no `MercadoLivreScraper`:**

```python
def _resolve_url(self, raw_url: str, card_html: str = "") -> tuple[str, str]:
    """Retorna (url_limpa, external_id).
    
    Resolve tracking URLs e garante external_id MLB válido.
    """
    external_id = self._extract_id_from_url(raw_url)

    if self._is_tracking_url(raw_url):
        dest = self._extract_tracking_destination(raw_url)
        if dest:
            raw_url = dest
            external_id = self._extract_id_from_url(dest) or external_id
        elif not external_id and card_html:
            # Fallback: achar MLB no HTML do card
            external_id = self._extract_id_from_text(card_html)

    if not external_id:
        return "", ""

    if not raw_url or self._is_tracking_url(raw_url):
        # Reconstrói URL canônica a partir do ID
        raw_url = f"https://carro.mercadolivre.com.br/MLB-{external_id[3:]}-_JM"

    url = self._strip_query_fragment(raw_url)
    return url, external_id
```

---

## Gap 5 — ML: `_unescape_ml` e escape específico do ML

**Onde está na v1:** `app/scrapers/mercadolivre.py::_unescape_ml`

**O que faz:** O ML emite strings com escapes específicos que o Python padrão não decodifica corretamente: `\u002F` (literal, não unicode real), `\/` (slash escapado em JSON). Sem isso, URLs chegam como `carro.mercadolivre.com.br\u002FMLB-123` ao invés de `carro.mercadolivre.com.br/MLB-123`.

**Copiar para a v2 integralmente:**
```python
def _unescape_ml(self, s: str) -> str:
    if not s:
        return ""
    s = (
        s.replace("\\u002F", "/")
         .replace("\\u003D", "=")
         .replace("\\u0026", "&")
         .replace("\\/", "/")
    )
    if re.search(r"\\u[0-9a-fA-F]{4}", s):
        try:
            s = s.encode("utf-8", "ignore").decode("unicode_escape")
        except Exception:
            pass
        s = s.replace("\\/", "/")
    return s
```

---

## Gap 6 — ML: fallback de preço via página VIP

**Onde está na v1:** `app/scrapers/mercadolivre.py::_extract_price_from_vip_html`, `_find_preloaded_state`, `_walk`

**O que faz:** Às vezes o ML omite o preço na listagem (item em negociação, preço sob consulta, etc.). A v1 detecta os itens sem preço após o parse e busca individualmente a página de detalhe (VIP) de até 5 desses itens para tentar recuperar o preço via `__PRELOADED_STATE__` (JSON embutido no HTML do VIP).

**Limite:** máximo de 5 chamadas VIP por run para não sobrecarregar o RPi.

**O que implementar no `MercadoLivreScraper.scrape` (sobrescrever o método base):**

```python
def scrape(self, search_url: str, ctx) -> ScraperResult:
    result = super().scrape(search_url, ctx)

    # Recuperação de preço via VIP (até 5 itens)
    missing_price = [l for l in result.listings if not l.get("price") and l.get("url")]
    for item in missing_price[:5]:
        try:
            vip_html = fetch_html(item["url"], ctx=ctx, timeout=20)
            price = self._extract_price_from_vip(vip_html)
            if price:
                item["price"] = price
        except Exception:
            pass

    return result
```

---

## Gap 7 — OLX: extração via `__NEXT_DATA__`

**Onde está na v1:** `app/scrapers/olx.py::_extract_next_data_json`

**O que faz:** OLX é um app Next.js. O HTML renderizado contém um `<script id="__NEXT_DATA__">` com todo o estado da página em JSON estruturado — incluindo listings com campos completos (preço, km, ano, localização, ID). Parsear esse JSON é muito mais confiável que scraping de HTML porque não depende de seletores CSS que mudam com redesigns.

**Estratégia v1:**
1. Tenta `BeautifulSoup.find("script", id="__NEXT_DATA__")` → `json.loads(tag.string)`
2. Fallback: regex `__NEXT_DATA__\s*=\s*({.*?})\s*;` no HTML bruto

**O que implementar no `OLXScraper.extract_raw_data`:**

```python
def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
    # Estratégia 1: __NEXT_DATA__ (mais confiável)
    next_data = self._extract_next_data(raw_content)
    if next_data:
        items = self._parse_from_next_data(next_data)
        if items:
            return items

    # Estratégia 2: BeautifulSoup fallback
    return self._parse_from_html(raw_content)

def _extract_next_data(self, html: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except Exception:
            pass
    # Fallback regex
    m = re.search(r'__NEXT_DATA__\s*=\s*(\{.*?\})\s*;', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None

def _parse_from_next_data(self, data: dict) -> List[Dict]:
    """Extrai listings do __NEXT_DATA__ (JSON estruturado).
    
    Navega: data.props.pageProps.listings[] ou equivalente.
    Usar _walk() para ser tolerante a mudanças de estrutura.
    """
    items = []
    for node in _walk(data):
        if not isinstance(node, dict):
            continue
        if node.get("listId") or node.get("list_id"):
            # parece um listing OLX
            items.append(node)
    return items
```

---

## Gap 8 — OLX: health tracking por arquivo (fallback rate 24h)

**Onde está na v1:** `app/scrapers/olx.py` — funções `olx_health_*`

**O que faz:** A v1 mantém um arquivo JSON em disco (`health/olx.json`) com:
- Timestamps dos últimos fallbacks para browser nas últimas 24h
- `force_browser_until_ts` — quando bloqueado, força 100% browser por N horas sem tentar HTTP
- Contador de fallbacks 24h — exposto no `/admin sources` como `thumb_rate` e `browser_fallback_24h`

Isso permite que o sistema aprenda automaticamente que o OLX está em período de bloqueio e pare de desperdiçar tentativas HTTP.

**O que implementar:** Esse padrão é específico do OLX mas o mecanismo é reutilizável. Criar `SourceHealthTracker` genérico na v2:

```python
# app/scrapers/shared/health_tracker.py (novo)
class SourceHealthTracker:
    """Rastreia saúde de uma source em arquivo JSON.
    
    Permite que scrapers registrem padrões de falha
    e tomem decisões adaptativas (ex: forçar browser por N horas).
    """
    def __init__(self, source: str):
        self.source = source
        self._path = health_dir() / f"{source}.json"
        self._lock = threading.Lock()

    def record_http_ok(self): ...
    def record_http_blocked(self): ...
    def record_browser_fallback(self): ...
    def force_browser_for(self, hours: int): ...
    def should_force_browser(self) -> bool: ...
    def fallback_count_24h(self) -> int: ...
    def get_stats(self) -> dict: ...
```

E no `OLXScraper`:
```python
def __init__(self):
    super().__init__("olx")
    self._health = SourceHealthTracker("olx")

def scrape(self, url, ctx) -> ScraperResult:
    if self._health.should_force_browser():
        ctx = replace(ctx, force_browser=True)
    result = super().scrape(url, ctx)
    if result.blocked:
        self._health.record_http_blocked()
        self._health.force_browser_for(hours=6)
    elif result.metrics.fetch_method == "hybrid":
        self._health.record_browser_fallback()
    else:
        self._health.record_http_ok()
    return result
```

---

## Gap 9 — iCarros: extração de ano e cidade pela URL

**Onde está na v1:** `app/scrapers/icarros.py::_extract_year_from_url`, `_slug_to_city_uf`, `_extract_location_from_url`

**O que faz:** iCarros codifica ano e cidade na própria URL do anúncio:
- `icarros.com.br/carros/honda-civic-si/2019/sao-paulo-sp/...` → ano=2019, cidade="São Paulo", UF="SP"

Isso permite recuperar esses campos mesmo quando o card da listagem não os exibe. Mais confiável que scraping de texto.

**O que implementar no `ICarrosScraper`:**

```python
def _extract_year_from_url(self, url: str) -> Optional[int]:
    m = re.search(r'/(\d{4})/', url or '')
    if m:
        year = int(m.group(1))
        if 1980 <= year <= 2030:
            return year
    return None

def _slug_to_city_uf(self, slug: str) -> Optional[str]:
    """Converte 'sao-paulo-sp' → 'São Paulo-SP'."""
    if not slug:
        return None
    parts = slug.rsplit('-', 1)
    if len(parts) == 2 and len(parts[1]) == 2 and parts[1].isalpha():
        city = parts[0].replace('-', ' ').title()
        uf = parts[1].upper()
        return f"{city}-{uf}"
    return None

def _extract_location_from_url(self, url: str) -> Optional[str]:
    """Extrai cidade/UF do path da URL."""
    try:
        path = urlparse(url).path
        # Formato: /carros/<modelo>/<ano>/<cidade-uf>/
        parts = [p for p in path.split('/') if p]
        for p in parts:
            loc = self._slug_to_city_uf(p)
            if loc:
                return loc
    except Exception:
        pass
    return None

def parse_listing(self, raw_data: dict) -> dict | None:
    url = raw_data.get("url", "")
    year = raw_data.get("year") or self._extract_year_from_url(url)
    location = raw_data.get("location") or self._extract_location_from_url(url)
    # ...
```

---

## Gap 10 — iCarros: extração robusta de km

**Onde está na v1:** `app/scrapers/icarros.py::_extract_km`

**O que faz:** O km no iCarros vem em formatos variados: `"87.000 km"`, `"87000km"`, `"87.000"`, `"87 mil km"`. A v1 tem regex para todos os casos.

**O que implementar:**

```python
def _extract_km(self, text: str) -> Optional[int]:
    if not text:
        return None
    text = text.lower().strip()
    # "87 mil km" → 87000
    m = re.match(r'(\d+[\.,]?\d*)\s*mil', text)
    if m:
        return int(float(m.group(1).replace(',', '.')) * 1000)
    # "87.000 km" ou "87000"
    m = re.match(r'(\d[\d\.,]+)', text)
    if m:
        raw = m.group(1).replace('.', '').replace(',', '')
        try:
            v = int(raw)
            if 100 <= v <= 999_999:
                return v
        except ValueError:
            pass
    return None
```

---

## Gap 11 — iCarros/Mobiauto: thumbnail com srcset e ranking de qualidade

**Onde está na v1:** `app/scrapers/icarros.py::_pick_from_srcset`, `_upgrade_image_url`, `_is_tiny_image`, `_extract_thumbnail_any`

**O que faz:** Imagens em srcset vêm como `url1 640w, url2 1024w, url3 1920w`. A v1 escolhe a melhor resolução (não a mais alta — limita em 1600px para evitar imagem enorme) e faz upgrade de URLs de thumb para versão maior quando o padrão é reconhecível.

**O que implementar:**

```python
def _pick_from_srcset(self, srcset: str, max_width: int = 1600) -> Optional[str]:
    """Escolhe a melhor URL de um srcset por largura."""
    if not srcset:
        return None
    best_url, best_w = None, 0
    for part in srcset.split(','):
        part = part.strip()
        tokens = part.split()
        if len(tokens) >= 2:
            url = tokens[0]
            try:
                w = int(tokens[1].rstrip('w'))
                if best_w < w <= max_width:
                    best_w, best_url = w, url
            except ValueError:
                pass
        elif len(tokens) == 1:
            best_url = best_url or tokens[0]
    return best_url

def _is_tiny_image(self, url: str) -> bool:
    """Detecta thumbnails minúsculas (placeholder/ícone)."""
    if not url:
        return True
    for marker in ('placeholder', 'blank', '1x1', 'transparent', 'pixel', 'icon'):
        if marker in url.lower():
            return True
    return False
```

---

## Gap 12 — `block_resources=True` hardcoded no fetcher v2

**Onde está no v2:** `app/scrapers/scraper_base/fetcher.py::_fetch_browser` — linha `block_resources = True`

**O que faz (problema):** Bloquear recursos (imagens, fontes, CSS) economiza RAM no RPi, mas alguns sites anti-bot (PerimeterX, Cloudflare) usam recursos externos como parte do desafio — se o JS de validação for bloqueado como "script de terceiro", o desafio falha silenciosamente.

**O que implementar:** tornar configurável por source via `source_configs.extra`:

```python
# No _fetch_browser:
block_resources = getattr(ctx, 'browser_block_resources', True)

# No source_configs.extra para fontes que precisam:
# {"browser_block_resources": false}  ← para Webmotors/PerimeterX
# {"browser_block_resources": true}   ← para GoGarage/iCarros (default seguro)
```

---

## Resumo por source — o que implementar antes de ativar dual

| Source | Gaps críticos (sem eles dual falha) | Gaps desejáveis |
|---|---|---|
| `mercadolivre` | Gap 3 (anti-peças), Gap 4 (tracking URLs), Gap 5 (unescape), Gap 2 (POLYCARD) | Gap 6 (VIP price fallback), Gap 1 (curl_cffi) |
| `olx` | Gap 7 (`__NEXT_DATA__`) | Gap 8 (health tracker), Gap 1 (curl_cffi) |
| `icarros` | Gap 9 (ano/cidade por URL), Gap 10 (km), Gap 11 (srcset) | Gap 1 (curl_cffi) |
| `mobiauto` | Gap 11 (srcset) | Gap 9 (adaptado), Gap 1 (curl_cffi) |
| `chavesnamao` | Nenhum crítico — v2 está próxima da v1 | Gap 1 (curl_cffi) |
| `gogarage` | Gap 12 (`block_resources=False`) | Gap 1 (curl_cffi) |
| `kavak` | Nenhum crítico | Gap 1 (curl_cffi) |

---

## Ordem de implementação recomendada

```
Sprint 1 — Fundação (afeta todas as sources)
├── Gap 1: curl_cffi no unified_fetch
└── Gap 12: block_resources configurável no fetcher

Sprint 2 — Mercado Livre (maior volume, maior impacto)
├── Gap 2: POLYCARD extraction + merge
├── Gap 3: filtro anti-peças
├── Gap 4: resolução de tracking URLs
└── Gap 5: _unescape_ml

Sprint 3 — OLX
├── Gap 7: __NEXT_DATA__ extraction
└── Gap 8: SourceHealthTracker genérico

Sprint 4 — iCarros + Mobiauto
├── Gap 9: ano e cidade por URL
├── Gap 10: extração de km
└── Gap 11: srcset picking

Sprint 5 — Validação via dual
├── Ativar dual para ML e OLX
├── Observar paridade 48–72h
└── Flipar para v2 quando paridade ≥ 95%
```

---

## Como medir paridade no modo dual

O `execute_dual_run` gera um relatório de comparação. Os campos relevantes:

```python
# Verificar no source_runs.payload após rodar dual
{
  "dual_report": {
    "v1_count": 18,
    "v2_count": 16,         # ← se < v1_count: gap real
    "only_in_v1": ["MLB123", "MLB456"],  # ← esses são os gaps
    "only_in_v2": [],
    "price_diff_count": 2,  # ← preços divergentes
    "paridade_pct": 88.9    # ← meta: ≥ 95% por 48h para flipar
  }
}
```

Consultar via admin:
```
/admin runall <source> --impl dual
```

---

*Documento gerado em 2026-05-21 com base em análise estática completa de v1 e v2.*
