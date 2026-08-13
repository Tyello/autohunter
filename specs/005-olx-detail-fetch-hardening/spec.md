# Spec: Hardened fetch para enriquecimento de thumbnail OLX (detail page)  [spec-kit: T2 — 5pts: arquivos=1, decisões=1, risco=1, novidade=1, verif=1]

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 12 iterações totais
- Parada: todos os REQs verdes | orçamento estourado → humano
- Registro: specs/005-olx-detail-fetch-hardening/RUN.md (append-only)

## Diagnóstico que motiva esta spec

Investigação confirmou, com dados reais (não hipotéticos):

1. `_extract_olx_detail_thumbnail` (adicionada no Prompt 2) extrai corretamente o `og:image`
   tanto da página real do Honda Civic Coupe 2015 (`.../honda-civic-coupe-si-2-4-16v-206cv-mec-2p-2015-1525422289`)
   quanto da página real do Audi A4 Avant 2019 já reportada antes — testado rodando a função
   diretamente contra o HTML real baixado desses dois anúncios. A extração NÃO é o problema.
2. Query direta no Postgres de produção (`car_listings` via `DATABASE_URL` do `.env`) mostra que
   **100% dos anúncios OLX criados nos últimos 30+ dias têm `thumbnail_url IS NULL`** (ex.: 2026-08-11:
   159/159 sem thumbnail; mesmo padrão em todos os dias desde pelo menos 2026-07-09). Isso é
   sistêmico, não um caso raro — o "fix" do Prompt 2 nunca funcionou em produção para nenhum anúncio novo.
3. Causa raiz identificada por leitura de código: `_enrich_missing_olx_thumbnails`
   (`app/scrapers/olx.py:284-309`) busca a página de detalhe com `fetch_html(...)` — o fetch
   **genérico/fraco** (`app/scrapers/base.py`), sem impersonation TLS (`curl_cffi`) nem os cookies
   aquecidos pelo Playwright. Já a busca da página de resultados (`_fetch_http_hybrid`,
   `app/scrapers/olx.py:463-523`) usa `cf_requests.get(..., impersonate=_OLX_IMPERSONATE)` +
   cookies de `_load_playwright_cookies_for_olx(ctx)`, e só assim consegue passar pelo
   anti-bot da OLX a partir de um IP de datacenter (produção). O fetch de detalhe, sem esse
   hardening, quase certamente recebe uma página de bloqueio/challenge (ou 403) em produção —
   `_extract_olx_detail_thumbnail` roda sobre essa página de bloqueio, não encontra `og:image`
   (porque não é a página real), e loga silenciosamente "no thumbnail found on detail page",
   quando na verdade é "bloqueado, nunca chegamos a ver a página real". O teste local funcionou
   porque rodou de um IP residencial/dev não bloqueado pela OLX — daí o fixture do Prompt 2
   "passar" sem cobrir o cenário real de produção.
4. O fixture de teste do Prompt 2 (`OLX_AUDI_A4_DETAIL_HTML` em
   `tests/test_olx_notification_thumbnail_logging.py`) é HTML sintético de 3 linhas com só a
   tag `og:image` — nunca exercitou o caminho de fetch (estava com o HTML já "pronto"), então
   não tinha como pegar esse bug: o bug está no fetch, não no parser.

## Objetivo
Fazer `_enrich_missing_olx_thumbnails` buscar a página de detalhe com o mesmo fetch hardened
(`cf_requests` + impersonation + cookies do Playwright) usado pela busca principal, com fallback
para `fetch_html` só quando `cf_requests` não está disponível — e logar de forma distinta quando
o fetch foi bloqueado (para não confundir "bloqueado" com "anúncio genuinamente sem foto"),
para permitir diagnosticar rapidamente qualquer falha real futura.

## Requisitos
- REQ-001: QUANDO `_enrich_missing_olx_thumbnails` busca a página de detalhe de um item sem
  thumbnail E `cf_requests` está disponível O SISTEMA DEVE buscar via `cf_requests.get(...,
  impersonate=_OLX_IMPERSONATE)` com os cookies de `_load_playwright_cookies_for_olx(ctx)` —
  verificado por: `pytest tests/test_olx_thumbnail_extraction.py -k hardened_fetch_used -q`
- REQ-002: QUANDO a página de detalhe retorna HTTP 403/429 OU o corpo bate com
  `_looks_like_cf_or_bot` O SISTEMA DEVE logar warning contendo a palavra "blocked" (distinto de
  "no thumbnail found") e NÃO deixar `_extract_olx_detail_thumbnail` rodar sobre a página de
  bloqueio — verificado por: `pytest tests/test_olx_thumbnail_extraction.py -k detail_fetch_blocked -q`
- REQ-003: QUANDO `cf_requests` não está disponível (ambiente sem a lib) O SISTEMA DEVE cair
  para `fetch_html` (comportamento atual), preservando o fallback — verificado por:
  `pytest tests/test_olx_thumbnail_extraction.py -k fallback_without_cf_requests -q`
- REQ-004: QUANDO a página de detalhe é buscada com sucesso e genuinamente não tem imagem
  extraível O SISTEMA DEVE continuar logando "no thumbnail found on detail page" (comportamento
  atual, mantido) — verificado por: teste existente
  `test_enrich_missing_olx_thumbnails_warns_when_detail_page_has_no_image` continua verde
- REQ-005: O parser `_extract_olx_detail_thumbnail` DEVE ser validado contra HTML real (não
  sintético) dos dois anúncios reais reportados (Honda Civic Coupe 2015, Audi A4 Avant 2019) —
  verificado por: `pytest tests/test_olx_thumbnail_extraction.py -k real_fixture -q` usando os
  fixtures `tests/fixtures/olx/honda_civic_coupe_2015_detail.html` e
  `tests/fixtures/olx/audi_a4_avant_2019_detail.html` (já criados e já contêm a tag `og:image`
  real capturada desses dois anúncios)

## Não-objetivos
- Não mexer no `_fetch_http_hybrid` da busca principal (já está correto).
- Não adicionar fallback via browser/Playwright para o fetch de detalhe (fora de escopo; o cap
  de 12 itens/execução já limita o volume, e o hardening HTTP deve resolver a maioria dos casos).
- Não mudar o valor do cap (`olx_detail_thumbnail_enrich_limit`).
- Não mudar `car_listings_repo.py` (upsert já prefere thumbnail quando NULL — correto).
- Não mudar `app/bot/sender.py` (já loga corretamente quando `thumbnail_url` está ausente —
  confirmado pelos testes existentes em `tests/test_olx_notification_thumbnail_logging.py`).

## Premissas assumidas (gate de fechamento)
- PREM-01: os dois fixtures HTML reais (`honda_civic_coupe_2015_detail.html`,
  `audi_a4_avant_2019_detail.html`) foram capturados diretamente das URLs reais reportadas pelo
  usuário via `curl` de um IP não bloqueado, truncados apenas removendo `<style>`/`<script>`
  irrelevantes (preservando todas as tags `<meta>` incluindo `og:image`) — representam
  fielmente a estrutura `<head>` real dessas páginas.
- PREM-02: como não há acesso ao processo de produção rodando (só ao Postgres via
  `DATABASE_URL`), a causa raiz (fetch de detalhe bloqueado) é a explicação mais provável dada a
  assimetria de hardening entre `_fetch_http_hybrid` (busca) e o fetch atual de
  `_enrich_missing_olx_thumbnails` (detalhe), combinada com 100% de falha sistêmica observada no
  banco — não uma prova direta via log de produção. O REQ-002 acrescenta logging que torna essa
  causa verificável no próximo ciclo real, conforme pedido pelo usuário.

## Decisões tomadas
- Extrair um helper novo `_fetch_olx_detail_html(url: str, ctx: ScrapeContext) -> str` dentro de
  `app/scrapers/olx.py`, espelhando o bloco `cf_requests` de `_fetch_http_hybrid` (linhas
  463-511), mas para uma única URL de item (sem o `time.sleep` de delay entre requisições de
  busca — mantém os delays já existentes em `_enrich_missing_olx_thumbnails`/`fetch_html`).
- Reusa `FetchBlocked`, `_looks_like_cf_or_bot`, `_load_playwright_cookies_for_olx`,
  `_OLX_IMPERSONATE`, `cf_requests` já importados/definidos no módulo.
- `_enrich_missing_olx_thumbnails` passa a chamar `_fetch_olx_detail_html(item.url, ctx)` no
  lugar de `fetch_html(item.url, ctx=ctx, referer=..., proxy=..., min_delay_ms=0,
  max_delay_ms=0)`. O `except FetchBlocked as exc` vira um branch específico que loga
  `"...detail page BLOCKED (%s): %s"` com `exc.status`/`exc.reason` (ou equivalente disponível
  em `FetchBlocked`); outras exceções mantêm a mensagem genérica atual ("failed to fetch/parse
  detail page").

## Etapas

### Etapa 1: criar fixtures reais de HTML (REQ-005)
- FAZ: já criados nesta investigação — apenas confirmar que existem e contêm `og:image`:
  `tests/fixtures/olx/honda_civic_coupe_2015_detail.html` e
  `tests/fixtures/olx/audi_a4_avant_2019_detail.html`. Nenhuma ação de código necessária além de
  verificar.
- TOCA: (nenhum — leitura)
- VALIDA COM: `grep -c "og:image" tests/fixtures/olx/honda_civic_coupe_2015_detail.html
  tests/fixtures/olx/audi_a4_avant_2019_detail.html` → ambos com contagem ≥ 1
- ESCALA SE: algum dos dois arquivos não existir ou não contiver `og:image`

### Etapa 2: adicionar `_fetch_olx_detail_html` hardened (REQ-001, REQ-002, REQ-003)
- FAZ: Em `app/scrapers/olx.py`, logo antes de `_enrich_missing_olx_thumbnails` (linha ~284),
  adicionar:
  ```python
  def _fetch_olx_detail_html(url: str, ctx: ScrapeContext) -> str:
      """Busca a pagina de detalhe com o mesmo hardening (TLS impersonation + cookies) usado
      na busca principal (_fetch_http_hybrid). Sem esse hardening, a OLX bloqueia o fetch de
      detalhe a partir de IPs de datacenter e o parser roda sobre uma pagina de bloqueio."""
      referer = "https://www.olx.com.br/"
      if cf_requests is not None:
          cookies = _load_playwright_cookies_for_olx(ctx)
          headers = {
              "User-Agent": (
                  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
              ),
              "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
              "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
              "Cache-Control": "no-cache",
              "Pragma": "no-cache",
              "Referer": referer,
          }
          proxies = None
          if ctx.proxy_server:
              proxies = {"http": ctx.proxy_server, "https": ctx.proxy_server}
          r = cf_requests.get(
              url,
              headers=headers,
              cookies=cookies or None,
              proxies=proxies,
              timeout=25,
              allow_redirects=True,
              impersonate=_OLX_IMPERSONATE,
          )
          status = int(getattr(r, "status_code", 0) or 0)
          text = getattr(r, "text", "") or ""
          if status in (403, 429):
              raise FetchBlocked(status, url, reason="http_status")
          if status == 200 and _looks_like_cf_or_bot(text):
              raise FetchBlocked(200, url, reason="bot_challenge")
          if status >= 400:
              raise FetchBlocked(status, url, reason="http_status")
          return text
      return fetch_html(url, ctx=ctx, referer=referer, proxy=ctx.proxy_server, min_delay_ms=0, max_delay_ms=0)
  ```
  Depois, dentro de `_enrich_missing_olx_thumbnails`, trocar a chamada atual:
  ```python
  html = fetch_html(item.url, ctx=ctx, referer="https://www.olx.com.br/", proxy=ctx.proxy_server, min_delay_ms=0, max_delay_ms=0)
  thumb = _extract_olx_detail_thumbnail(html, item.url)
  ```
  por:
  ```python
  html = _fetch_olx_detail_html(item.url, ctx=ctx)
  thumb = _extract_olx_detail_thumbnail(html, item.url)
  ```
  e separar o tratamento de exceção em dois `except` (o bloco atual é um único
  `except Exception as exc:`): primeiro `except FetchBlocked as exc:` logando
  `logger.warning("_enrich_missing_olx_thumbnails: detail page BLOCKED for %s (status_code=%s reason=%s)", item.url, exc.status_code, exc.reason)`
  (`FetchBlocked.__init__(self, status_code: int, url: str, *, reason: str | None = None)` em
  `app/scrapers/base.py:17` — atributos confirmados: `exc.status_code`, `exc.url`, `exc.reason`),
  depois `except Exception as exc:` mantendo a mensagem genérica atual
  ("failed to fetch/parse detail page %s: %s"). Em ambos os casos, `thumb = None` continua
  sendo setado para preservar o comportamento de fallback. Nota: `FetchBlocked` deve estar
  importado no módulo `app/scrapers/olx.py` (já é usado em `_fetch_http_hybrid`, então já está
  disponível no escopo do arquivo).
- TOCA: `app/scrapers/olx.py`
- VALIDA COM: `python -c "from app.scrapers.olx import _fetch_olx_detail_html"` sem erro de
  importação; `pytest tests/test_olx_notification_thumbnail_logging.py tests/test_olx_thumbnail_extraction.py -q`
  (suíte existente) passa 100% (nenhuma regressão)
- ESCALA SE: `python -c "from app.scrapers.olx import _fetch_olx_detail_html"` falhar com
  `ImportError`/`NameError` (indica que `cf_requests`, `FetchBlocked`, `_looks_like_cf_or_bot`,
  `_load_playwright_cookies_for_olx` ou `_OLX_IMPERSONATE` não estão no escopo do módulo como
  a spec assume)

### Etapa 3: testes cobrindo o fetch hardened e o bloqueio distinto (REQ-001, REQ-002, REQ-003)
- FAZ: Criar `tests/test_olx_thumbnail_extraction.py` (novo arquivo) com:
  1. `test_real_fixture_honda_civic_2015_extracts_thumbnail` — carrega
     `tests/fixtures/olx/honda_civic_coupe_2015_detail.html`, chama
     `_extract_olx_detail_thumbnail(html, url)` com a URL real do anúncio, assert que retorna
     `"https://img.olx.com.br/images/43/433605438030577.jpg"`.
  2. `test_real_fixture_audi_a4_2019_extracts_thumbnail` — mesma coisa com
     `tests/fixtures/olx/audi_a4_avant_2019_detail.html` e URL do Audi, assert
     `"https://img.olx.com.br/images/48/488699432043826.jpg"`.
  3. `test_enrich_uses_hardened_fetch_when_cf_requests_available` — monkeypatcha
     `olx_module.cf_requests` com um fake objeto cujo `.get(...)` retorna um response fake
     (status_code=200, text=HTML fixture do Honda), chama
     `_enrich_missing_olx_thumbnails([...item sem thumbnail...], ScrapeContext(source="olx"),
     limit=1)`, assert que (a) `cf_requests.get` foi chamado (ex.: via um `calls: list` no fake)
     com `impersonate=` presente nos kwargs, (b) `item.thumbnail_url` foi preenchido
     corretamente.
  4. `test_enrich_falls_back_to_fetch_html_when_cf_requests_none` — monkeypatcha
     `olx_module.cf_requests = None` e `olx_module.fetch_html` para um fake que retorna a
     fixture HTML, assert que `fetch_html` foi chamado e o thumbnail foi preenchido.
  5. `test_enrich_logs_blocked_distinctly_from_no_image` — monkeypatcha
     `olx_module.cf_requests` com um fake cujo `.get(...)` retorna `status_code=403`, chama
     `_enrich_missing_olx_thumbnails(...)` com `caplog`, assert que existe um record com
     `"blocked"` na mensagem (case-insensitive) e que NÃO existe um record com
     `"no thumbnail found on detail page"` para esse item (prova que bloqueio não é confundido
     com "sem imagem genuína").
  Usar o mesmo padrão de fakes (`_FakeResponse`-like, `monkeypatch`) já usado em
  `tests/test_olx_notification_thumbnail_logging.py` para consistência de estilo.
- TOCA: `tests/test_olx_thumbnail_extraction.py` (novo)
- VALIDA COM: `pytest tests/test_olx_thumbnail_extraction.py -v` → 5 testes, todos verdes
- ESCALA SE: a mensagem de log real produzida pela Etapa 2 não contiver a palavra "blocked"
  (case-insensitive) após 2 tentativas de ajustar o assert ao texto exato logado

### Etapa 4: rodar suíte completa e confirmar ausência de regressão
- FAZ: Rodar a suíte completa de testes do projeto relacionados a OLX e ao sender/media (nenhuma
  mudança de escopo, só validação).
- TOCA: (nenhum)
- VALIDA COM: `pytest tests/test_olx_notification_thumbnail_logging.py tests/test_olx_thumbnail_extraction.py -q`
  → todos verdes (suíte antiga + suíte nova, sem nenhuma falha/erro)
- ESCALA SE: qualquer teste da suíte antiga (`test_olx_notification_thumbnail_logging.py`)
  quebrar — indica que a mudança da Etapa 2 alterou comportamento fora do escopo (ex.: mudou a
  mensagem de log que os testes antigos verificam com `"no thumbnail found"`)

## Critérios de aceitação globais
1. Todos os REQ-001..REQ-005 cobertos por teste com evidência (arquivo:linha)
2. Suíte completa verde: `pytest tests/test_olx_notification_thumbnail_logging.py tests/test_olx_thumbnail_extraction.py -q` (9 testes: 6 existentes + 5 novos, mas 2 dos "novos" REQ-005 fixture tests substituem/complementam — total declarado: 5 testes existentes em test_olx_notification_thumbnail_logging.py permanecem + 5 novos em test_olx_thumbnail_extraction.py = 10 testes... nota: contar o valor real reportado pelo pytest ao final, este número é só a expectativa mínima)
