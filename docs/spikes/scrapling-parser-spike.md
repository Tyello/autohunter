# Spike: parser Scrapling vs BeautifulSoup no OLX

Spec: `specs/023-scrapling-parser-spike/spec.md`. Modo read-only: nenhuma linha de `app/`, `migrations/`, `requirements*.txt`, `config/` ou `deploy/` foi alterada nesta spike.

## 0. Status da pré-condição

**Fechado.** O bug de parse/enrichment do OLX (perda de `year`/`mileage_km`/condição/FIPE antes do scoring) foi corrigido, revisado e deployado em produção antes desta spike começar:

- `specs/021-olx-year-mileage-extraction/spec.md` — todas as 5 etapas aprovadas.
- Commit `b085acc` (extração de `year`/`km` do título) + commit `cb0e9bd` (fix de tipo `str`→`int` para as colunas `Integer` de `car_listings`).
- Evidência de produção em `specs/021-olx-year-mileage-extraction/RUN.md` (entrada de 2026-09-05): ciclo de ingest OLX das 03:23:33 UTC gravou `year` corretamente em `car_listings` (ex.: Land Rover Defender 2024, Honda Civic 2008); `mileage_km` fica `NULL` só quando o título genuinamente não contém km.

## 1. Inventário de parse (BeautifulSoup em `app/scrapers/**` e `app/sources/**`)

| Arquivo:linha | Parser | O que extrai | Caminho |
|---|---|---|---|
| `app/scrapers/olx.py:252` | `html.parser` | `og:image`/`twitter:image` da página de detalhe (thumbnail) | frio |
| `app/scrapers/olx.py:363` | `html.parser` | `__NEXT_DATA__` JSON (com fallback por regex) | quente |
| `app/scrapers/olx.py:757` | `html.parser` | Cards de anúncio (fallback se `__NEXT_DATA__` indisponível) | quente |
| `app/scrapers/mercadolivre.py:347` | `lxml` | Link `canonical`/`og:url` de detalhe | frio |
| `app/scrapers/mercadolivre.py:552` | `lxml` | `__PRELOADED_STATE__` JSON | quente |
| `app/scrapers/mercadolivre.py:617` | `lxml` | Preço via SSR (fallback) | quente |
| `app/scrapers/mercadolivre.py:715` | `lxml` | Cards de anúncio (listing) | quente |
| `app/scrapers/chavesnamao.py:165` | `html.parser` | Título/preço/local de tags `<a>` | quente |
| `app/scrapers/chavesnamao.py:242` | `html.parser` | `og:image`/`twitter:image` (enriquecimento de thumbnail) | frio |
| `app/scrapers/turboclass.py:179` | `html.parser` | Links de anúncio | quente |
| `app/scrapers/auctions/generic_auction.py:64` | `lxml` | Eventos de leilão | quente |
| `app/scrapers/auctions/generic_auction.py:183` | `lxml` | Lotes de leilão | quente |
| `app/scrapers/sources/olx.py:85` | `lxml` | Cards via `data-ds-component='DS-AdCard'` | quente, mas **desconectado de produção** |
| `app/scrapers/sources/chavesnamao.py:48` | `lxml` | Vehicle cards (trilha v2) | quente (v2) |
| `app/scrapers/sources/icarros.py:63` | `lxml` | Cards de carros (trilha v2) | quente (v2) |
| `app/scrapers/sources/mercadolivre.py:102` | `lxml` | Items polycard (trilha v2) | quente (v2) |
| `app/scrapers/sources/turboclass.py:41` | `lxml` | Links de anúncio (trilha v2) | quente (v2) |
| `app/scrapers/sources/webmotors.py:64` | `lxml` | Cards via `data-type='car-card'` (trilha v2) | quente (v2), WebMotors despriorizada (AGENTS.md) |
| `app/scrapers/sources/gogarage_mobiauto.py:32` | `lxml` | Vehicle cards (trilha v2) | quente (v2) |
| `app/scrapers/sources/gogarage_mobiauto.py:145` | `lxml` | Vehicle cards, segundo método (trilha v2) | quente (v2) |

**Scraper OLX ativo em produção:** `scrape_olx` (`app/scrapers/olx.py`), registrado em `app/sources/builtins.py:80-84` (`SourcePlugin(name="olx", ..., scrape=scrape_olx, ...)`). A classe `OLXScraper` (`app/scrapers/sources/olx.py`) está desconectada do fluxo de produção — usa API própria da OLX, não HTML/`__NEXT_DATA__`/RSC — conforme já documentado em `specs/021-olx-year-mileage-extraction/spec.md:12`. Os demais arquivos em `app/scrapers/sources/**` fazem parte da trilha v2/dual-run (ver AGENTS.md, "V1→V2 é trilha técnica incremental").

## 2. Resultados do benchmark

Máquina: PC de desenvolvimento Windows, Python 3.13.3, execução local (não a máquina de produção). Script: `scripts/spikes/bench_scrapling_parser.py`, ≥100 execuções por fixture/variante, `time.perf_counter` para mediana/p95, `tracemalloc` para pico de memória.

Comando pronto para rodar no Raspberry Pi de produção (não executado nesta spike — sem acesso à máquina):
```bash
python -m venv .venv-spike
.venv-spike/bin/pip install scrapling==0.4.15 beautifulsoup4 lxml
.venv-spike/bin/python scripts/spikes/bench_scrapling_parser.py
```

| Fixture | Variante | Mediana (ms) | P95 (ms) | Pico memória (MB) |
|---|---|---|---|---|
| audi_a4_avant_2019_detail.html | (a) BS4 html.parser | 5.02–5.26 | 5.73–8.29 | 0.2742 |
| audi_a4_avant_2019_detail.html | (b) BS4 lxml | 3.08–3.13 | 3.65–3.72 | 0.0565 |
| audi_a4_avant_2019_detail.html | (c) Scrapling Selector | 0.30–0.32 | 0.34–0.58 | 0.0088 |
| honda_civic_coupe_2015_detail.html | (a) BS4 html.parser | 4.86–5.14 | 5.32–5.67 | 0.0541 |
| honda_civic_coupe_2015_detail.html | (b) BS4 lxml | 3.00–3.18 | 3.72–3.85 | 0.0536 |
| honda_civic_coupe_2015_detail.html | (c) Scrapling Selector | 0.28–0.29 | 0.30–0.32 | 0.0033 |
| honda_civic_coupe_2015_detail_share_placeholder.html | (a) BS4 html.parser | 0.70–0.71 | 0.75–0.78 | 0.0138 |
| honda_civic_coupe_2015_detail_share_placeholder.html | (b) BS4 lxml | 0.66–0.73 | 0.89–0.92 | 0.0153 |
| honda_civic_coupe_2015_detail_share_placeholder.html | (c) Scrapling Selector | 0.16 | 0.18–0.40 | 0.0036 |
| honda_civic_hatch_1993_detail.html | (a) BS4 html.parser | 0.74–0.75 | 0.89 | 0.0140 |
| honda_civic_hatch_1993_detail.html | (b) BS4 lxml | 0.64 | 0.75–0.99 | 0.0151 |
| honda_civic_hatch_1993_detail.html | (c) Scrapling Selector | 0.16 | 0.17–0.18 | 0.0036 |
| search_rsc_price_nodes.html (~15 KB, caminho de busca/RSC) | (a) BS4 html.parser | 3.35–3.68 | 4.06–4.15 | 2.1514 |
| search_rsc_price_nodes.html | (b) BS4 lxml | 3.46–4.06 | 3.96–4.88 | 2.1529 |
| search_rsc_price_nodes.html | (c) Scrapling Selector | 2.67–3.61 | 3.22–4.11 | 2.1295 |

**Leitura importante:** o ganho de scrapling não é uniforme. Nas 4 fixtures de página de **detalhe** (thumbnail `og:image`, `__NEXT_DATA__` pequeno, fallback de cards em HTML pequeno), (c) é **~15-17x mais rápido** que (a) e usa **~3-30x menos memória de pico**. Na fixture de **busca/RSC** (`search_rsc_price_nodes.html`, ~15 KB — representativa do caminho quente de maior volume, onde `_extract_next_data_json`/extração de chunks RSC processa a página de resultados a cada scrape), o ganho cai para **~1.0-1.1x**, e a memória de pico é praticamente idêntica entre as 3 variantes (~2.15 MB nos três casos — esse valor não vem do tamanho do arquivo, que é pequeno; é overhead de import/estruturas intermediárias comum às 3 variantes, não investigado a fundo nesta spike). Isso indica que, nessa operação específica, o gargalo é a extração via regex sobre o blob JSON bruto — não a escolha do parser de árvore HTML. Trocar o parser não ataca esse gargalo.

### Validação em hardware real (Raspberry Pi 4 Model B, 4 GB, produção)

Rodado após a spike, via SSH (`pi@192.168.0.146`), em venv isolada (`/tmp/spike-bench`, fora do checkout de produção em `/opt/autohunter`), mesmas 5 fixtures, mesmo script, sem alterações:

| Fixture | Variante | Mediana (ms) |
|---|---|---|
| audi_a4_avant_2019_detail.html | (a) BS4 html.parser | 18.53 |
| audi_a4_avant_2019_detail.html | (b) BS4 lxml | 11.61 |
| audi_a4_avant_2019_detail.html | (c) Scrapling Selector | 0.80 |
| search_rsc_price_nodes.html | (a) BS4 html.parser | 6.63 |
| search_rsc_price_nodes.html | (b) BS4 lxml | 6.74 |
| search_rsc_price_nodes.html | (c) Scrapling Selector | 4.55 |

O padrão se confirma no hardware real, com margem ainda mais clara pela CPU mais fraca: nas fixtures de detalhe, (b) lxml já dá ~1.6x sobre (a) e (c) scrapling dá ~23x; na fixture de busca/RSC (caminho quente), (c) scrapling fica em ~1.45x sobre (a) — ainda longe do critério de 5x para GO, e (b) lxml não ajuda nesse caso (6.74ms vs 6.63ms, dentro da margem de ruído). **Confirma o veredito NO-GO da seção 6.**

Teste adicional, isolando só o short-circuit implementado (ver seção 7): como `search_rsc_price_nodes.html` não contém a substring `__NEXT_DATA__` (confirmado — 0 ocorrências, é o estado real das páginas de busca da OLX hoje), pular o parse antes de procurar essa tag deu **~248x** de ganho nessa operação específica isolada (0.778 ms/chamada → 0.0031 ms/chamada, média de 100 execuções na Pi), porque elimina inteiramente a construção da árvore HTML quando a tag não existe — o que é o caso em toda página de busca atual.

## 3. Equivalência semântica

Campos comparados por fixture: `image_og_meta`, `title_og_meta`, `price_og_meta`, `has_next_data`, `rsc_chunk_count`, `card_count` (conforme o que as operações reais de `app/scrapers/olx.py:252,363,757` extraem).

**Nenhuma divergência.** Em todas as 5 fixtures, todo campo comparado tem valor idêntico entre (a) BS4 `html.parser` e (c) `scrapling.Selector` (ex.: `image_og_meta` e `title_og_meta` batem byte a byte nas 4 fixtures de detalhe; `rsc_chunk_count=1` em ambas as variantes na fixture de busca). Nenhuma exceção foi lançada pela variante (c) em nenhuma fixture.

**Limitação metodológica registrada:** `card_count` ficou `None`/vazio nas 5 fixtures em ambas as variantes — as fixtures de "detail" não contêm cards de listagem (são páginas de anúncio único) e a fixture de busca usa RSC (não HTML de cards clássico com `data-testid="adcard-link"`), então o seletor de fallback de cards (`app/scrapers/olx.py:757`) não tem, nestas fixtures específicas, nenhum card real para casar. Isso não invalida a equivalência semântica medida (ambas as variantes concordam em "zero cards" nestas fixtures), mas significa que o caminho de fallback de cards não foi exercitado com dados positivos nesta spike — recomendação: se a migração avançar, validar esse caminho especificamente com uma fixture que contenha `data-testid="adcard-link"` real antes de promover.

## 4. Modo adaptive (exploratório)

Teste em duas rodadas, já que nenhuma fixture do repo contém `data-ds-component` (confirmado via busca — esse atributo é usado só em `app/scrapers/sources/olx.py:85`, código v2 desconectado, não nas fixtures de `app/scrapers/olx.py`):

1. **`search_rsc_price_nodes.html`** (renomeando chaves JSON `listId`→`adItemId`, `subject`→`adTitle`, `priceValue`→`adPrice`): `Selector(html, adaptive=True).css('div', auto_save=True)` no original, depois `.css('div', adaptive=True)` no renomeado. Resultado: **1 de 2 elementos recuperados (50%)**, 0 falsos positivos.
2. **HTML sintético de 2 cards** (classes `card-item`/`card-title`/`card-price`/`card-location` → `listing-box`/`listing-name`/`listing-amount`/`listing-area`): seletor antigo sem adaptive no HTML renomeado recupera 0/2 (0%); com `adaptive=True`, recupera **1/2 (50%)**; `find_similar()` retorna um objeto válido mas não amplia a recuperação além do 1º elemento. 0 falsos positivos em ambos os testes.

**Resultado confirma o limite documentado do scrapling**: o storage adaptive salva apenas o **primeiro** elemento de cada seleção — por isso a taxa de recuperação trava em 50% com exatamente 2 cards, e cairia proporcionalmente mais (1/N) com mais cards por página. Nenhum arquivo de storage SQLite persistente foi criado no ambiente durante os testes (rodados fora do repo versionado, no scratchpad da sessão).

**Recomendação:** o modo adaptive, como está nesta versão do scrapling, **não é utilizável** para recuperar múltiplos cards de uma página de busca/listagem (o caso de uso central do scraper OLX) sem lógica adicional própria (ex.: reimplementar auto-save para todos os elementos, não só o primeiro). Não contar com adaptive como mitigação de fragilidade de seletor nesta adoção.

## 5. Custo de adoção

Resumo por arquivo (ver tabela completa do inventário na seção 1 para os 20 pontos):

| Arquivo | Linhas/funções estimadas | Risco ADR-0001 | Por quê | Testes afetados |
|---|---|---|---|---|
| `app/scrapers/olx.py:252` | 7–10 | Não | Só thumbnail (frio); não contribui para `external_id` | indireto: `test_olx_thumbnail_extraction.py` |
| `app/scrapers/olx.py:363` | 4–5 | Não | Extrai JSON; `external_id` é derivado de valores dentro do JSON, não da seleção em si | indireto: `test_olx_price_extraction.py`, `test_scraper_parsing.py` |
| `app/scrapers/olx.py:757` | 15–20 | **Sim** | Fallback extrai `href` usado para construir `external_id` via regex; dedupe depende disso | direto: `test_olx_force_browser_config.py`, `test_scraper_parsing.py`, `test_scrapers_contract.py` |
| `app/scrapers/mercadolivre.py` (4 pontos) | 20–26 no total | **Sim** (cards/URL) | `external_id` extraído de `href`/URL do card | `test_scrapers_contract.py`, `test_scraper_parsing.py`, `test_ingest_dedupe.py` |
| `app/scrapers/chavesnamao.py` (2 pontos) | 25–32 no total | **Sim** (cards) | `href` alimenta regex de `external_id` | `test_scrapers_contract.py`, `test_scraper_parsing.py` |
| `app/scrapers/turboclass.py:179` | 20–22 | **Sim** | `href` → `external_id` | `test_scrapers_contract.py`, `test_scraper_parsing.py` |
| `app/scrapers/auctions/generic_auction.py` (2 pontos) | 20–24 no total | **Sim** | `event_id`/`lot_id` dependem de card/link | nenhum teste dedicado hoje (piloto controlado) |
| `app/scrapers/sources/**` (9 pontos, trilha v2) | 15–20 cada | Sim, mas **risco atual baixo** (v2 desconectado de produção); risco sobe se promovido sem `dual_run` | `external_id` via `href`/URL quando ativo | nenhum (v2 não ativa hoje) |

Testes que mencionam OLX: 4 diretos (`test_olx_*.py`) + ~60 indiretos (contrato/integração/matching que citam `"olx"` em fixtures ou dados de exemplo). `tests/source_regression` citado no prompt original **não existe neste repo** — usado `grep -rln "olx" tests/` como substituto (registrado aqui, não omitido).

**Padrão de mudança:** troca é mecanicamente 1:1 na maioria dos pontos (`BeautifulSoup(html, parser)` → `Selector(html)`; `.select()/.select_one()` → `.css()`; `.get_text()` → `.text_content()`; `.get("attr")` → `.attrib.get("attr")`), mas é significativa em volume nos pontos que constroem `href`/`external_id` (15-20 linhas cada), porque ali a extração de atributo alimenta diretamente a chave de dedupe — exatamente o tipo de mudança que o ADR-0001 pede para tratar com cautela ("na dúvida, não colapsar").

## 6. Decisão go/no-go

**NO-GO** para migração completa do parser OLX para scrapling nesta rodada.

Critérios do prompt original aplicados aos números da seção 2:

- **GO** exigiria (c) ≥5x mais rápido que (a) **e** 0 divergências **e** mudança localizada. 0 divergências ✓ (seção 3) e mudança tecnicamente localizada ao scraper ✓ (seção 5), mas o ganho de velocidade **não é uniforme**: ~15-17x nas 4 fixtures de página de detalhe, mas apenas ~1.0-1.1x na fixture de busca/RSC — que é a que representa o caminho quente de maior volume (processada a cada scrape, contra páginas de detalhe que são acessadas com muito menos frequência). Como o critério GO precisa valer para "as mesmas operações que o código real faz" no agregado, e a operação de maior peso no custo real de CPU do Pi (extração RSC da página de busca) não atinge nem perto de 5x, o critério GO **não é satisfeito**.
- **"Só trocar para lxml"** também não se aplica: na fixture de busca/RSC, (b) BS4 lxml é na verdade **mais lento** que (a) html.parser (3.46-4.06ms vs 3.35-3.68ms) — o custo de construir a árvore lxml não compensa quando a extração real é feita majoritariamente por regex sobre o blob JSON, não por travessia de árvore.
- Portanto **NO-GO**: nenhuma troca de parser ataca o gargalo real da operação de maior volume (regex sobre JSON/RSC bruto), então o ganho medido não justifica o custo de adoção (seção 5: ~15-20 linhas por ponto que toca `external_id`, sob o risco de ADR-0001) nem em `app/scrapers/olx.py` nem nos demais scrapers do inventário.

**Ressalva registrada, não uma recomendação de ação:** nos pontos genuinamente "frios" e dominados por parsing de árvore (extração de `og:image` em página de detalhe, leitura de `__NEXT_DATA__` pequeno), scrapling entrega ganho real (~15-17x, memória ~3-30x menor) sem risco de ADR-0001 (não tocam `external_id`). Se o custo de CPU dessas operações frias se tornar relevante no futuro (ex.: aumento de volume de enriquecimento de thumbnail), vale reavaliar uma adoção pontual e isolada a esses caminhos frios — não como parte desta decisão, e não implementada aqui.

Não há plano de migração incremental a detalhar (seção 6 do prompt original), dado o veredito NO-GO.

## 7. Otimizações implementadas (fora do escopo original da spike, pós-decisão)

Com o veredito NO-GO para scrapling, mas com dados de equivalência já coletados, duas otimizações **sem adicionar dependências novas** (`lxml` já é dependência do projeto) foram implementadas e validadas em `app/scrapers/olx.py`:

1. **Troca de parser `html.parser` → `lxml`** em `_extract_olx_detail_thumbnail` (linha ~252, frio) e `_extract_next_data_json` (linha ~363, quente) — equivalência de saída confirmada empiricamente nas 5 fixtures (og:image, `__NEXT_DATA__`, cards) antes da mudança. **Não** aplicada em `_fallback_parse_from_cards` (linha ~757) — sem cobertura de teste com HTML real de card para provar equivalência, e é o ponto que alimenta `external_id`/dedupe (risco ADR-0001).
2. **Short-circuit em `_extract_next_data_json`**: `if "__NEXT_DATA__" not in html: return None` antes de instanciar o parser — estritamente equivalente (o regex de fallback também exige essa substring literal), pois a OLX migrou para RSC streaming e a tag `__NEXT_DATA__` não aparece mais nas páginas de busca atuais (confirmado: 0 ocorrências em `search_rsc_price_nodes.html`).

Validação: `pytest tests/ -k olx` → 25 passed (suíte completa relacionada a OLX, sem alteração de asserção). Validação em hardware real (seção 2): short-circuit isolado mede **~248x** de ganho na operação que ele evita, medido na Pi de produção via SSH em venv isolada fora do checkout de produção.

Diff aplicado (`app/scrapers/olx.py`):
```diff
 def _extract_olx_detail_thumbnail(html: str, detail_url: str) -> str | None:
-    soup = BeautifulSoup(html or "", "html.parser")
+    soup = BeautifulSoup(html or "", "lxml")
     for selector in ('meta[property="og:image"]', 'meta[name="twitter:image"]', 'meta[property="twitter:image"]'):
...
 def _extract_next_data_json(html: str) -> Optional[dict]:
     """
     Tenta extrair o JSON do <script id="__NEXT_DATA__" type="application/json">...</script>
     (padrão Next.js). Se não achar, tenta fallback por regex.
     """
-    soup = BeautifulSoup(html, "html.parser")
+    if "__NEXT_DATA__" not in html:
+        return None
+    soup = BeautifulSoup(html, "lxml")
```
