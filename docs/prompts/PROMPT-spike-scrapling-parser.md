# Prompt Claude Code — Spike: parser Scrapling vs BeautifulSoup no OLX

> **Pré-condição:** executar **somente depois** que o bug do parse/enrichment do OLX (perda de km/ano/condição/FIPE antes do scoring) estiver fechado. Se ainda estiver aberto, pare e reporte isso na seção 0 do entregável.

## Modo de operação

- **READ-ONLY no código da aplicação.** Não altere nada em `app/`, `migrations/`, `requirements*.txt`, `config/` nem `deploy/`.
- Única escrita permitida: o entregável (`docs/spikes/scrapling-parser-spike.md`) e o script de benchmark descartável em `scripts/spikes/bench_scrapling_parser.py`.
- Instale o Scrapling **só em venv separado** (`.venv-spike/`), com `pip install scrapling` (apenas o parser — **não** instale `scrapling[fetchers]`, nem rode `scrapling install`, nem baixe browsers).
- Toda afirmação sobre o código precisa de citação `arquivo:linha`.

## Contexto (não reconstrua; use isto)

- Produto: AutoHunter / Garagem Alvo. Alertas de anúncios de carros via Telegram. Python 3.13, FastAPI, SQLAlchemy, APScheduler, Playwright.
- Produção: **Raspberry Pi 4 (4 GB)**. **Restrições de design obrigatórias:**
  1. A CPU do Pi é fraca → o custo de parse importa.
  2. O Supabase é remoto → nenhuma proposta pode adicionar round-trips ao banco.
  3. O Chromium consome muita memória → nenhuma proposta pode adicionar browser.
- ADRs relevantes:
  - **ADR-0001** (dedup por chaves canônicas; "na dúvida, não colapsar"). O spike **não pode** alterar `external_id`/URL canônica.
  - **ADR-0002** (async só para scraping HTTP-first; DB async fora de escopo). O spike é só de parse e não mexe em I/O.
- Scrapling (v0.4.15, BSD-3, Python ≥3.10): `from scrapling.parser import Selector`. API: `.css()`, `.xpath()`, pseudo-elementos `::text`/`::attr()`, `.get()`/`.getall()`, `find_all()` no estilo BS4 e `find_similar()`. Modo adaptive: `Selector(html, adaptive=True, url=...)` + `css(sel, auto_save=True)` / `css(sel, adaptive=True)`, com storage em SQLite local. **Limite conhecido:** o adaptive salva só o **primeiro** elemento de cada seleção.

## Pontos conhecidos para começar (confirme e expanda)

- `app/scrapers/olx.py:16` importa BeautifulSoup. Há usos com `"html.parser"` (não lxml) em `:252` (`_extract_olx_detail_thumbnail`) e `:363` (`_extract_next_data_json`).
- `app/scrapers/sources/olx.py`: parse JSON (`:65`) com fallback CSS de cards (`:90-133`, `DS-AdCard`, `DS-Price`, `DS-Location`…).
- Fixtures: `tests/fixtures/olx/*.html` (4 páginas de detalhe + `search_rsc_price_nodes.html`).
- Comparação v1×v2: `app/scrapers/dual_run.py` (`compare_results`).

## Tarefas

1. **Inventário de parse.** Liste todos os pontos em `app/scrapers/**` e `app/sources/**` que usam BeautifulSoup. Para cada um, informe: `arquivo:linha`, o parser usado (`html.parser`/`lxml`), o que ele extrai e se está no caminho quente (rodado a cada scrape) ou frio (fallback/enriquecimento). Deixe explícito quais dos dois arquivos OLX está ativo em produção hoje e por quê (cite o registry/adapters).
2. **Benchmark offline** (`scripts/spikes/bench_scrapling_parser.py`). Com as fixtures OLX, compare:
   - (a) BS4 `html.parser`, como está hoje;
   - (b) BS4 `lxml`, a troca mais barata possível;
   - (c) `scrapling.Selector`.

   Meça, para as mesmas operações que o código real faz (localizar `__NEXT_DATA__`/RSC, selecionar os cards e extrair título/preço/local/imagem/atributos): tempo mediano e p95 com ≥100 execuções, e pico de memória (`tracemalloc`). O script tem de rodar sem alterações também no Pi (sem dependências além de `bs4`, `lxml` e `scrapling`).
3. **Equivalência semântica.** Para cada fixture, os campos extraídos por (c) devem ser **idênticos** aos de (a). Qualquer divergência vai para uma tabela: campo, valor antes, valor depois, causa.
4. **Adaptive (exploratório).** Numa cópia da fixture de busca, renomeie as classes/atributos `data-ds-component` dos cards. Teste se `css(..., adaptive=True)` + `find_similar()` recupera **todos** os cards, e não só o primeiro. Reporte a taxa de recuperação e os falsos positivos.
5. **Custo de adoção.** Estime quantas linhas/funções mudariam por scraper, o risco para o ADR-0001 (id e URL canônica) e o impacto nos testes existentes (`tests/**olx**`, `tests/source_regression`).

## Entregável único

`docs/spikes/scrapling-parser-spike.md`, com:

0. Status da pré-condição (bug de parse do OLX fechado? evidência).
1. Inventário (tabela com `arquivo:linha`).
2. Resultados do benchmark: tabela a/b/c com mediana, p95 e memória, informando a máquina (PC; Pi se possível; se não for possível, deixe o comando pronto para rodar no Pi).
3. Equivalência semântica (tabela de divergências, ou "nenhuma").
4. Adaptive: resultado e recomendação.
5. **Decisão go/no-go** com os indicadores:
   - **GO** se (c) for ≥5x mais rápido que (a) **e** tiver 0 divergências de campo **e** a mudança for localizada no scraper;
   - **"só trocar para lxml"** se (b) já capturar a maior parte do ganho;
   - **NO-GO** caso contrário.
6. Se for GO: plano de migração incremental (um scraper por vez, validado pelo `dual_run` antes de promover) e a lista exata de arquivos a alterar. **Não implemente.**
