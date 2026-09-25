# Spec: Spike — parser Scrapling vs BeautifulSoup no OLX  [spec-kit: T2 — 5pts: arquivos=2 (1pt), decisões=0 (0pt), risco=0/isolado-readonly (0pt), novidade=2/lib+harness novos (2pt), verif=2/exige script novo (2pt)]

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco (todas as etapas desta spec são leitura/análise/relatório → auto-aprovadas, exceto a etapa 3, que cria código novo de benchmark e passa por `spec-reviewer`)
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 12 iterações totais
- Parada: todos os REQs verdes | orçamento estourado → humano
- Registro: specs/023-scrapling-parser-spike/RUN.md (append-only)

## Pré-condição (já verificada nesta sessão de planejamento)

O bug de parse/enrichment do OLX (perda de `year`/`mileage_km`/condição/FIPE antes do scoring) está **fechado**: spec `specs/021-olx-year-mileage-extraction/spec.md`, todas as 5 etapas aprovadas, commits `b085acc` e `cb0e9bd` (fix de tipo `str`→`int`), deploy no Pi de produção e verificado em `RUN.md` da spec 021 em 2026-09-05 (`year` populado corretamente em `car_listings` no ciclo de ingest OLX das 03:23:33 UTC). Esta evidência deve ser citada tal como está na seção 0 do entregável — não reabrir investigação.

## Objetivo
Produzir um spike **read-only** que decide, com evidência mensurável (benchmark offline + equivalência semântica), se vale trocar BeautifulSoup por `scrapling.parser.Selector` no parsing do OLX — sem alterar nenhum código de aplicação.

## Requisitos
- REQ-001: O entregável DEVE conter, na seção 0, o status da pré-condição com a evidência acima — verificado por: leitura de `docs/spikes/scrapling-parser-spike.md`.
- REQ-002: O entregável DEVE conter tabela de inventário (arquivo:linha, parser, o que extrai, caminho quente/frio) cobrindo todo uso de `BeautifulSoup` em `app/scrapers/**` e `app/sources/**`, e DEVE declarar explicitamente qual dos dois arquivos OLX (`app/scrapers/olx.py` vs `app/scrapers/sources/olx.py`) está ativo em produção, citando o registry — verificado por: grep `BeautifulSoup` em `app/scrapers` e `app/sources` batendo 1:1 com as linhas da tabela.
- REQ-003: `scripts/spikes/bench_scrapling_parser.py` DEVE existir, importar só `bs4`, `lxml` e `scrapling`, rodar sozinho (sem código de `app/`) via `.venv-spike/Scripts/python scripts/spikes/bench_scrapling_parser.py`, medir tempo mediano e p95 (≥100 execuções) e pico de memória (`tracemalloc`) para (a) BS4 `html.parser`, (b) BS4 `lxml`, (c) `scrapling.Selector`, nas fixtures `tests/fixtures/olx/*.html`, sobre as operações reais (localizar `__NEXT_DATA__`/RSC, selecionar cards, extrair título/preço/local/imagem/atributos) — verificado por: execução do script e inspeção da tabela impressa.
- REQ-004: O entregável DEVE conter tabela de equivalência semântica por fixture comparando os campos extraídos por (a) e (c) ("nenhuma" se não houver divergência) — verificado por: leitura da seção 3 do entregável.
- REQ-005: O entregável DEVE reportar o teste exploratório do modo adaptive (renomear classes/atributos `data-ds-component` numa cópia da fixture de busca, testar `css(..., adaptive=True)` + `find_similar()`), com taxa de recuperação e falsos positivos — verificado por: leitura da seção 4 do entregável.
- REQ-006: O entregável DEVE conter estimativa de custo de adoção (linhas/funções por scraper, risco para ADR-0001 sobre `external_id`/URL canônica, impacto em testes existentes que citam OLX) — verificado por: leitura da seção 5.
- REQ-007: O entregável DEVE terminar com decisão GO / "só trocar para lxml" / NO-GO aplicando os critérios do prompt original de forma explícita e, se GO, um plano de migração incremental (um scraper por vez, validado por `app.scrapers.dual_run.compare_results` antes de promover) sem implementar nada — verificado por: leitura da seção 6.
- REQ-008: Nenhuma alteração DEVE existir em `app/`, `migrations/`, `requirements*.txt`, `config/`, `deploy/` ao final da spike — verificado por: `git diff --stat -- app/ migrations/ requirements.txt requirements-dev.txt config/ deploy/` vazio.

## Não-objetivos
- Não implementar a migração para scrapling em nenhum scraper real.
- Não instalar `scrapling[fetchers]`, não rodar `scrapling install`, não baixar browsers.
- Não alterar `external_id`/URL canônica de nenhum anúncio (ADR-0001).
- Não tocar `app/scrapers/dual_run.py` nem qualquer outro arquivo de `app/` — só ler.
- Não rodar o benchmark no Raspberry Pi de produção nesta sessão (sem acesso); apenas deixar o comando pronto.

## Premissas assumidas (gate de fechamento)
- PREM-01: A pré-condição já foi verificada nesta sessão de planejamento (ver seção acima) — a etapa 1 apenas transcreve essa evidência para o entregável, não reinvestiga.
- PREM-02: "Máquina" no benchmark = a máquina onde o executor efetivamente roda o script (PC de desenvolvimento Windows). O comando para rodar no Pi fica documentado e pronto, mas não é executado nesta spike.
- PREM-03: Instalação isolada via `python -m venv .venv-spike` na raiz do repo + `.venv-spike/Scripts/pip install scrapling==0.4.15` (pin exato pela versão citada no prompt original, para reprodutibilidade). Sem `[fetchers]`.
- PREM-04: `.gitignore` hoje só cobre `.venv/` (linha 4), não `.venv-spike/` — a etapa final deve adicionar essa entrada para não deixar a venv rastreável, sem tocar em mais nada do arquivo.
- PREM-05: `tests/source_regression` citado no prompt original não existe como diretório neste repo (confirmado via listagem) — a etapa de custo de adoção deve usar `grep -rln "olx" tests/` (lista já levantada nesta sessão) como substituto e registrar essa divergência no entregável em vez de referenciar um caminho inexistente.

## Decisões tomadas
- Escopo de escrita restrito a exatamente 2 arquivos de produto (`docs/spikes/scrapling-parser-spike.md`, `scripts/spikes/bench_scrapling_parser.py`) + `.gitignore` (1 linha) + `.venv-spike/` (não versionado) — qualquer necessidade de tocar outro arquivo é motivo de escalação, não decisão local.
- Toda afirmação sobre código no entregável leva citação `arquivo:linha` — etapas de leitura devem coletar essas citações à medida que avançam, não no fim.
- `scrape_olx` (`app/scrapers/olx.py`) é o scraper ativo em produção, registrado em `app/sources/builtins.py:80-84` (`SourcePlugin(name="olx", ..., scrape=scrape_olx, ...)`); `app/scrapers/sources/olx.py` (classe `OLXScraper`) está desconectado do fluxo de produção, conforme já documentado em `specs/021-olx-year-mileage-extraction/spec.md:12` — a etapa 2 só precisa confirmar e citar essa linha, não redescobrir.

## Etapas

### Etapa 1: Criar venv de spike isolada
- FAZ: Rodar `python -m venv .venv-spike` na raiz do repo, depois `.venv-spike/Scripts/pip install scrapling==0.4.15` (Windows). Não instalar `scrapling[fetchers]`, não rodar `scrapling install`.
- TOCA: nenhum arquivo do repo (só cria diretório `.venv-spike/`, tratado na etapa 8).
- VALIDA COM: `.venv-spike/Scripts/python -c "from scrapling.parser import Selector; print('ok')"` deve imprimir `ok` sem baixar nenhum browser.
- ESCALA SE: a instalação falhar por incompatibilidade de versão do Python (rodar `python --version` antes; scrapling exige Python ≥3.10) — decisão sobre versão residual.

### Etapa 2: Inventário de uso de BeautifulSoup  (REQ-002)
- FAZ: `grep -rn "BeautifulSoup" app/scrapers app/sources` (ignorando `__pycache__`); para cada ocorrência de código-fonte real, abrir o arquivo no ponto citado e classificar: parser (`html.parser`/`lxml`), o que extrai, caminho quente (roda a cada scrape) ou frio (fallback/enriquecimento). Confirmar e citar `app/sources/builtins.py:80-84` como o registro que ativa `scrape_olx` (`app/scrapers/olx.py`) em produção, e `specs/021-olx-year-mileage-extraction/spec.md:12` como a evidência de que `app/scrapers/sources/olx.py` (`OLXScraper`) está desconectado do fluxo de produção.
- TOCA: nenhuma edição de código — só leitura. Guardar a tabela para a etapa 7.
- VALIDA COM: tabela cobre pelo menos `app/scrapers/olx.py:252,363,757` e qualquer outra ocorrência encontrada pelo grep em `app/scrapers/**`/`app/sources/**`, cada linha com `arquivo:linha`, parser, extração, quente/frio.
- ESCALA SE: não for possível determinar com confiança, a partir do registry, qual dos dois arquivos OLX está ativo em produção.

### Etapa 3: Escrever benchmark script  (REQ-003)
- FAZ: Criar `scripts/spikes/bench_scrapling_parser.py` que, usando `tests/fixtures/olx/audi_a4_avant_2019_detail.html`, `tests/fixtures/olx/honda_civic_coupe_2015_detail.html`, `tests/fixtures/olx/honda_civic_coupe_2015_detail_share_placeholder.html`, `tests/fixtures/olx/honda_civic_hatch_1993_detail.html` e `tests/fixtures/olx/search_rsc_price_nodes.html`, implementa e mede (≥100 execuções cada, `time.perf_counter` para mediana/p95, `tracemalloc` para pico de memória) as 3 variantes: (a) BS4 `html.parser`, (b) BS4 `lxml`, (c) `scrapling.parser.Selector`. As operações medidas devem replicar as reais de `app/scrapers/olx.py` (localizar `__NEXT_DATA__`/dados RSC, selecionar cards via seletor CSS equivalente, extrair título/preço/local/imagem/atributos) sem importar `app/`. Imprimir uma tabela final por fixture x variante com mediana, p95 e pico de memória.
- TOCA: `scripts/spikes/bench_scrapling_parser.py` (novo arquivo).
- VALIDA COM: `.venv-spike/Scripts/python scripts/spikes/bench_scrapling_parser.py` roda sem erro e imprime a tabela completa (5 fixtures x 3 variantes).
- ESCALA SE: replicar as operações reais do parser OLX exigir lógica ambígua não coberta pelas 4 operações citadas no prompt original (localizar dados embutidos, selecionar cards, extrair os 5 campos) — decisão sobre o que fica de fora da medição.

### Etapa 4: Rodar benchmark e levantar equivalência semântica  (REQ-004)
- FAZ: Rodar o script da etapa 3 e capturar a saída completa. Para cada fixture, comparar campo a campo os valores extraídos por (a) e por (c); preencher tabela campo / valor antes / valor depois / causa para cada divergência encontrada (ou "nenhuma" se todas baterem).
- TOCA: nenhuma edição de código — resultado vai para a etapa 7.
- VALIDA COM: saída bruta do benchmark + tabela de equivalência preenchida (mesmo que vazia, com "nenhuma" explícito).
- ESCALA SE: (c) lançar exceção não tratada em alguma fixture — registrar como divergência com o traceback, não tentar corrigir o parser scrapling.

### Etapa 5: Teste exploratório do modo adaptive  (REQ-005)
- FAZ: Copiar `tests/fixtures/olx/search_rsc_price_nodes.html` para um arquivo temporário fora do repo versionado (ex. no scratchpad da sessão), renomear as classes/atributos `data-ds-component` dos cards nessa cópia. Rodar `Selector(html_original, adaptive=True, url=...)` com `css(seletor_original, auto_save=True)` sobre o HTML original, depois `css(seletor_original, adaptive=True)` + `find_similar()` sobre a cópia renomeada. Contar quantos cards são recuperados versus o total real, e listar falsos positivos (elementos recuperados que não são cards de anúncio).
- TOCA: nenhuma edição em `app/`; o HTML renomeado fica fora do controle de versão.
- VALIDA COM: contagem "N recuperados / total real" e lista de falsos positivos (ou "nenhum") registrada para a etapa 7.
- ESCALA SE: o storage SQLite local do modo adaptive não puder ser isolado do restante do ambiente — reportar a limitação tal como observada, não contornar.

### Etapa 6: Estimar custo de adoção  (REQ-006)
- FAZ: Para cada ocorrência do inventário da etapa 2, estimar linhas/funções que mudariam ao trocar para `scrapling.Selector`. Avaliar risco para ADR-0001 verificando se algum ponto de parse contribui para `external_id` ou URL canônica do anúncio (buscar onde essas chaves são montadas em `app/scrapers/olx.py`). Listar arquivos de teste afetados via `grep -rln "olx" tests/` (excluindo `__pycache__` e fixtures `.html`) — usar essa lista como substituto de `tests/source_regression`, que não existe neste repo (PREM-05), e registrar essa divergência do prompt original no entregável.
- TOCA: nenhuma edição de código.
- VALIDA COM: lista com arquivo, linhas/funções estimadas, risco ADR-0001 (sim/não + por quê), testes afetados.
- ESCALA SE: nenhuma condição esperada (etapa de levantamento mecânico).

### Etapa 7: Consolidar entregável final  (REQ-001, REQ-002, REQ-004, REQ-005, REQ-006, REQ-007)
- FAZ: Escrever `docs/spikes/scrapling-parser-spike.md` com as seções 0-6 na ordem do prompt original: 0) status da pré-condição com a evidência da seção "Pré-condição" desta spec; 1) tabela de inventário da etapa 2; 2) tabela de benchmark a/b/c da etapa 3-4 com mediana, p95, memória, informando a máquina ("PC" + specs de CPU/RAM se disponíveis via `systeminfo`/equivalente) e o comando pronto para rodar no Pi (`.venv-spike/Scripts/python scripts/spikes/bench_scrapling_parser.py` executado localmente no Pi após criar a venv lá); 3) tabela de equivalência semântica da etapa 4; 4) resultado e recomendação do teste adaptive da etapa 5; 5) decisão GO (se (c) ≥5x mais rápido que (a) E 0 divergências de campo E mudança localizada no scraper) / "só trocar para lxml" (se (b) já capturar a maior parte do ganho) / NO-GO (caso contrário), aplicando os números medidos sem arredondar a favor de nenhum lado; 6) se GO: plano de migração incremental (um scraper por vez, validado por `app.scrapers.dual_run.compare_results` antes de promover) e lista exata de arquivos a alterar — sem implementar nada.
- TOCA: `docs/spikes/scrapling-parser-spike.md` (novo arquivo).
- VALIDA COM: arquivo existe, contém as 7 seções (0-6) na ordem, toda afirmação sobre código tem citação `arquivo:linha`, seção 5 declara veredito GO / só-lxml / NO-GO de forma explícita e inequívoca.
- ESCALA SE: os números do benchmark não permitirem aplicar os critérios do veredito sem ambiguidade (ex. ganho de (c) entre 4x e 6x, ou divergências presentes mas triviais) — escalar para decisão humana em vez de arredondar.

### Etapa 8: Confirmar escopo read-only e limpar
- FAZ: Rodar `git status --short` e `git diff --stat -- app/ migrations/ requirements.txt requirements-dev.txt config/ deploy/`; ambos devem confirmar que nada fora do escopo autorizado foi tocado. Adicionar `.venv-spike/` ao `.gitignore` (nova linha, sem alterar mais nada do arquivo) para não deixar a venv rastreável.
- TOCA: `.gitignore` (1 linha nova).
- VALIDA COM: `git status --short` mostra apenas `docs/spikes/scrapling-parser-spike.md`, `scripts/spikes/bench_scrapling_parser.py` e `.gitignore`; `git diff --stat -- app/ migrations/ requirements.txt requirements-dev.txt config/ deploy/` vazio.
- ESCALA SE: o diff mostrar qualquer alteração fora dos 3 arquivos esperados — parar imediatamente e reportar ao usuário, não corrigir sozinho.

## Critérios de aceitação globais
1. Todos os REQ-001 a REQ-008 cobertos com evidência (`arquivo:linha` para afirmações de código, comando+saída para benchmark/testes).
2. `git status --short` ao final mostra exatamente: `docs/spikes/scrapling-parser-spike.md`, `scripts/spikes/bench_scrapling_parser.py`, `.gitignore` (1 linha) — nada em `app/`, `migrations/`, `requirements*.txt`, `config/`, `deploy/`.
