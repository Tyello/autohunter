# Detector de bloqueio anti-bot (vendored Crawl4AI) — 2026-10-20

## 1. Achados da Fase 0 (`arquivo:linha`, antes da mudança)

- `app/scrapers/base.py:335-340`: `fetch_html`/`fetch_response` já levantava `FetchBlocked` com `http_status` (403/429) e `bot_challenge` (200 + heurística `_looks_like_bot_challenge`, `base.py:130-157`).
- Cópia quase idêntica da heurística em `app/services/browser_fetcher.py:111-133` (usada em `:298` e `:431`).
- `app/scrapers/fetching.py:14-20`: `_is_blocked_error` aceitava só 403/429 e `reason in {bot_challenge, http_status}`.
- `app/services/playwright_pool.py:750-760`: o loop de espera (até 10 × ~1,2 s) usava substrings soltas (`"captcha"`, `"cloudflare"`, …). Nunca levanta `FetchBlocked`.
- Chamadores de `fetch_html_with_browser_fallback`: turboclass, gogarage, mercadolivre, kavak, chavesnamao, mobiauto. **OLX e iCarros não passam por ele**: OLX tem fetch próprio (`olx.py:324`, `:694`) e heurística própria `_looks_like_cf_or_bot` (`olx.py:589`).
- `app/scrapers/scraper_base/fetcher.py:75`: usa `base.fetch_html`, herda a mudança.
- Divergências do prompt original: `tests/scrapers/` não existe (testes planos em `tests/`); havia fixtures de Kavak, Mobiauto e iCarros; `THIRD_PARTY_NOTICES.md` e `docs/reports/` não existiam.

## 2. Diff resumido

| Arquivo | Mudança |
|---|---|
| `app/scrapers/shared/antibot_detector.py` (novo) | Vendor de `crawl4ai/antibot_detector.py` @ `30165f1…` (sha256 `c72f772e…62e0`, Apache-2.0, LICENSE conferido). `is_blocked(..., *, structural=False, local=True)`: o check "200 quase vazio" e o Tier 3 só rodam com `structural=True`. Adicionados `_LOCAL_PATTERNS` (porte exato da heurística antiga), `local_block_reason`, `shadow_reason`. Padrões e Tier 1/2 intactos. |
| `app/scrapers/base.py` | `classify_block()` (único ponto de decisão): legado → `bot_challenge`; Tier 1/2/status → `antibot:<reason>`; ignora padrões Crawl4AI se content-type não é HTML (JSON). `_looks_like_bot_challenge` virou view booleana. `record_antibot_shadow()` registra `ctx.antibot_shadow_tier3` e loga, sem bloquear. Varredura Crawl4AI limitada aos primeiros 150 000 chars. |
| `app/services/browser_fetcher.py` | Cópia da heurística removida; importa de `base.py`. Shadow no HTML do browser. |
| `app/scrapers/fetching.py` | `_is_blocked_error` reconhece `antibot:*`; `_hybrid_block_reason` no ctx + log; último recurso passa por `classify_block` e levanta `blocked_after_browser_fallback`; shadow no HTML devolvido. |
| `app/services/playwright_pool.py` | Loop de espera usa `is_blocked(structural=False)`; continua só esperando. |
| `app/scrapers/olx.py` | Nos dois caminhos `curl_cffi` (`:324`, `:694`): após a checagem existente, `classify_block` → `FetchBlocked(reason="antibot:…")`; shadow registrado. Parse intocado. |
| `THIRD_PARTY_NOTICES.md`, `docs/reports/` | Novos. |
| `tests/test_antibot_detector.py` | Novo (53 testes). |

## 3. Testes

- Novos: 53 passam. Cobrem positivos (Cloudflare form/JS, PerimeterX, DataDome, Akamai, Incapsula), 429/403, JSON, content-type não HTML, 9 detecções legadas preservadas, integração em `fetching.py` (warmup acionado por `antibot:*`; challenge nunca chega ao parser) e em `base.fetch_html`.
- Negativos: 18 fixtures reais/aparados (OLX, Chaves na Mão, GoGarage, Kavak, Mobiauto, iCarros, TurboClass, ML) retornam `False` com `structural=False`.
- Tier 3 documentado: 9 fixtures legítimos retornam `True` com `structural=True` (5 da OLX, 3 do iCarros, 1 do ML), com o shell RSC `olx/search_rsc_price_nodes.html` como caso principal. É o motivo de o Tier 3 estar desligado. Nenhum fixture foi alterado.
- Suíte completa após as mudanças e após a otimização do custo (seção 4): **2304 passaram, 3 skipped, 0 falharam** nas duas rodadas (contagem pelos caracteres de progresso do pytest; esta versão não imprimiu a linha-resumo com `-q`).
- Baseline antes das mudanças: terminou com exit code 0, mas não capturei a contagem.

## 4. Custo do detector (máquina de dev, não o Pi; melhor de 5 rodadas × 30 chamadas, em ms)

Mesma máquina e mesmos HTMLs (`tests/fixtures/source_regression/*/2026-09-28_civic/listing.html`). Colunas:
**legado** = heurística antiga de `base.py` @ `5d561b5` (o que já existia); **classify** = decisão atual (`classify_block`);
**cls+sombra** = o que o fetch paga por resposta (`classify_block` + `shadow_reason`).

| Fonte | KB | legado | classify (antes → depois) | cls+sombra antes | cls+sombra depois |
|---|---|---|---|---|---|
| TurboClass | 109 | 1,08 | 5,19 → 5,18 | 9,29 | 5,30 |
| Kavak | 333 | 3,56 | 10,00 → 9,76 | 16,82 | 9,73 |
| GoGarage | 444 | 4,39 | 9,44 → 9,35 | 16,47 | 9,55 |
| Mobiauto | 709 | 8,08 | 12,74 → 12,58 | 20,80 | 12,69 |
| Chaves na Mão | 733 | 7,35 | 12,06 → 11,81 | 20,48 | 11,85 |
| OLX | 1806 | 16,51 | 19,62 → 19,56 | 24,01 | 19,76 |

**Otimização aplicada.** `lower()` já rodava uma única vez por chamada de `classify_block` (o Tier 3 usa regex com
`IGNORECASE`, não `lower()`), então não havia o que reaproveitar ali. O desperdício real era `shadow_reason` chamar
`is_blocked(structural=True)`, que **repetia a varredura Tier 1/2** (incluindo o strip de `<script>/<style>`) já feita por
`classify_block`: ≈ +4 a +8 ms por resposta. Agora a sombra roda só as checagens de casca vazia/Tier 3 (`_structural_checks`,
extraídas sem alterar a lógica), custando ≈ 0,1 ms. Resultado: o custo por resposta caiu de 9–24 ms para 5–20 ms, sem
mudar nenhuma decisão de bloqueio.

**Quanto o detector somou ao que já existia** (cls+sombra depois − legado): TurboClass +4,2 ms, Kavak +6,2, GoGarage +5,2,
Mobiauto +4,6, Chaves na Mão +4,5, OLX +3,3. Esse acréscimo é basicamente o strip de `<script>/<style>` do Tier 1
(≈ 4–5 ms em 700 KB, já limitado aos primeiros 150 000 chars).

**A meta de < 5 ms não foi atingida em páginas grandes**, e a maior parte do custo (7–16 ms) é a heurística legada, que já
existia. Varredura não foi limitada nas palavras-chave antigas (decisão: nenhuma detecção pode ser perdida). No Pi o
custo será maior; o tempo médio real lá deve ser medido na validação pós-deploy.

## 5. Riscos e pendências

- **Tier 3 desligado** por falsos positivos; só opera em modo sombra (`antibot_shadow_tier3`). Fixtures aparados à mão podem não refletir respostas reais; revisar após o período de sombra.
- **Lacuna conhecida:** `mercadolivre/2026-09-28_civic/listing_shell_com_cookies_bloqueado.html` (bloqueio real do ML) **não é detectado** pelos Tiers 1 e 2 (travado em teste). ML segue fora de escopo.
- O check "200 quase vazio" do Crawl4AI também foi movido para `structural=True`.
- 503 não passa por `classify_block` em `fetch_html` (a condição existente é só 200; 403/429 já levantavam).
- Custo acima da meta (seção 4).
- Fase 4 (`tools/schema_gen/`) **não foi feita** (opcional).
- Cobertura de Kavak/Mobiauto/iCarros restrita aos fixtures aparados existentes; sem coleta ao vivo.
- Nenhum fixture legítimo ficou próximo do Tier 2 (nenhum disparo de Tier 1/2 em qualquer fixture).

## 6. Validação pós-deploy (48 h)

Contar por fonte nos logs: `hybrid_fetch_blocked … reason=antibot:*`, `hybrid_fetch_blocked_after_browser_fallback`, e `antibot_shadow_tier3=`. Critérios: (a) `antibot:*` em páginas que antes parseavam bem indica falso positivo, então reverter o padrão; (b) volume de `antibot_shadow_tier3` por fonte decide se o Tier 3 pode virar decisão; (c) separar bloqueio de falha de parse no diagnóstico da OLX. Só então avançar.
