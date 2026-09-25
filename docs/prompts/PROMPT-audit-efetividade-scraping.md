# Prompt Claude Code — Auditoria: efetividade e eficiência do scraping

## Modo de operação

- **READ-ONLY** em `app/`, `migrations/`, `config/`, `deploy/` e `requirements*.txt`. Nenhuma migração, nenhuma alteração de schema, nenhum deploy.
- Escritas permitidas:
  - o entregável único: `docs/spikes/scraping-efetividade-audit.md`;
  - scripts descartáveis de sondagem em `scripts/spikes/` (prefixo `probe_`).
- **Rede:** permitido só no item 4, com **no máximo 30 requisições no total**, intervalo ≥2s entre elas e respeitando o `robots.txt`. **Proibido** qualquer bypass, solver ou proxy.
- Toda afirmação sobre o código precisa de citação `arquivo:linha`. Toda afirmação sobre a rede precisa do comando executado e do status HTTP.
- Se algo não puder ser confirmado, marque **NÃO VERIFICADO**. Não infira.

## Contexto (não reconstrua; use isto)

- AutoHunter / Garagem Alvo: alertas de anúncios de carros de entusiasta via Telegram. Python 3.13, FastAPI, SQLAlchemy/Alembic, APScheduler, curl_cffi e Playwright.
- **Restrições obrigatórias de design:**
  1. **Raspberry Pi 4 (4 GB):** CPU fraca.
  2. **Supabase é remoto:** cada query é um round-trip de rede. Nenhuma proposta pode adicionar queries por anúncio.
  3. **Chromium consome muita memória:** toda proposta deve **reduzir** o uso de browser, nunca aumentar.
- ADRs:
  - **ADR-0001** (dedup por chave canônica; "na dúvida, não colapsar"; `source_url_cursors` como chave implícita).
  - **ADR-0002** (async só no scraping HTTP-first; DB async fora de escopo).
- Decisão anterior: o spike do Scrapling (`docs/spikes/scrapling-parser-spike.md`, seção 6) deu **NO-GO**. **Não proponha Scrapling nem outro framework de crawler/parser.** Qualquer proposta deve usar o que já existe (curl_cffi, lxml/bs4, APScheduler e as filas atuais).
- O que já existe (confirme e cite):
  - cursor incremental (`app/scheduler/jobs.py:80`, `:257-263`);
  - circuit breaker (`app/scrapers/shared/circuit_breaker.py`);
  - `Retry-After` (`app/scrapers/base.py:57`);
  - fallback híbrido HTTP→browser (`app/scrapers/fetching.py`);
  - `parse_failure` por contagem (`app/scrapers/parse_failure.py`);
  - `dual_run` (`app/scrapers/dual_run.py`);
  - `force_browser` por fonte;
  - enfileiramento com `next_due` (`app/scheduler/run.py:182`, `:213`).
- Lição registrada: o bug do OLX (km/ano/FIPE sumindo antes do scoring) passou despercebido porque só a **contagem** de anúncios era monitorada, não o **preenchimento dos campos**.

## Investigações

### 1. Monitor de preenchimento por campo (field coverage)
- Mapeie onde cada execução de scrape é registrada (`record_run`, `scrape_job`, health). Informe quais métricas por execução existem hoje.
- Para cada fonte ativa, liste os campos críticos (`price`, `year`, `km`, `city/UF`, `thumbnail`, `external_id`, `url`) e onde eles são preenchidos (`arquivo:linha`).
- Verifique se já existe algum cálculo de percentual de preenchimento por campo, em qualquer lugar (incluindo `specs/020-score-v2-data-completeness` e `specs/021-*`).
- Proponha o desenho: onde calcular (em memória, no fim do adapter), onde persistir (**reaproveitando o payload do `record_run`, sem nova tabela se possível**), limites iniciais por campo e fonte, e o canal de alerta (admin no Telegram). Estime o custo em queries por execução (deve ser 0 ou 1).
- Pergunta-chave: **com esse monitor, o bug do OLX teria sido detectado? Em quanto tempo?** Responda com base no fluxo real.

### 2. Taxa de captura (recall)
- Verifique se existe hoje alguma medição do tipo "anúncios que existiam vs capturados". Espera-se que não exista; confirme.
- Proponha um método barato, fora de pico, sem browser, para estimar o recall por fonte. Opções a avaliar:
  - (a) sitemaps oficiais (ver item 4);
  - (b) busca ampla de referência paginada, comparada às URLs em `listings`;
  - (c) comparar com os anúncios recebidos no `dual_run`.
- Para cada opção: custo em requisições/dia, custo em queries ao Supabase (**em lote, nunca por anúncio**) e confiabilidade da medição.

### 3. Frequência adaptativa por busca
- Descreva exatamente como o `next_due` é calculado hoje (`run.py`, `source_configs`, filas) e se o intervalo é por fonte, por URL de busca ou por wishlist.
- Com os dados existentes (execuções, cursor e `first_seen` dos anúncios), verifique se é possível calcular a **taxa de anúncios novos por URL de busca**. Diga quais colunas/tabelas sustentam o cálculo, **sem executar queries pesadas no Supabase**. Se precisar de amostra, use no máximo 1 query agregada com `LIMIT`.
- Proponha uma política: faixas de intervalo mínimo e máximo, como subir e descer o intervalo, e as proteções necessárias (intervalo máximo para buscas de usuário Premium, orçamento de requisições por fonte e dia).
- Estime a redução de requisições/dia e o efeito na latência do alerta.

### 4. Descoberta via sitemap (sondagem de rede limitada)
- A partir do Pi (ou do ambiente disponível; informe qual), usando o curl_cffi já instalado:
  - `https://www.webmotors.com.br/robots.txt` e `https://www.webmotors.com.br/sitemap/v2/sitemaps-DA-index.xml`;
  - **1 arquivo** `DA-index-HONDA.xml.gz`: status HTTP, tamanho, número de `<loc>`, formato de URL, presença de `<lastmod>` por URL e se "DA" é mesmo a página de detalhe do anúncio;
  - **1 URL de detalhe** tirada desse arquivo, via HTTP simples: status, se veio desafio do PerimeterX e se há dados estruturados (`ld+json`, `__NEXT_DATA__` ou JSON embutido) com preço, ano e km;
  - `https://www.olx.com.br/sp/sitemap_index.xml`: estrutura, se há sitemaps de anúncios de autos, frequência de atualização e formato de URL.
- Registre a conformidade: o `robots.txt` da OLX tem `Disallow: /api/`. Cite onde o scraper atual usa `/api/v1/search/listings` (`app/scrapers/sources/olx.py:31` e onde mais houver) e se esse caminho está **ativo** em produção.
- Veredito por fonte: **o sitemap serve como (i) descoberta de anúncios novos, (ii) referência para medir recall, (iii) ambos, ou (iv) nenhum?** Para o Webmotors: isso reabre a fonte sem passar pela busca protegida?

### 5. Ordem de extração e escada de escalonamento
- Para cada scraper ativo (confirme pelo registry/adapters quais são v1 e v2 e quais estão ligados), classifique a fonte de dados usada: API interna, JSON embutido (`__NEXT_DATA__`/RSC/`ld+json`), CSS ou browser. Aponte onde já existe JSON disponível mas o código ainda usa CSS.
- Mapeie a escada atual (curl_cffi → retry → browser) por fonte e onde o estado "precisa de browser" é memorizado (`olx_health_force_browser`, `source_configs.force_browser`). Esse estado é generalizado ou específico do OLX?
- Avalie a inclusão do **wreq** (`pip install wreq`, que tem wheel para aarch64) como degrau entre o curl_cffi e o browser: onde entraria (`app/scrapers/base.py`/`fetching.py`), o que precisaria mudar e o risco. **Não instale nem teste em produção.** Se testar, faça em venv separado e no máximo contra o `robots.txt` das fontes.
- Liste as fontes que usam browser hoje e estime quanto de memória/CPU cairia se cada uma passasse para JSON/HTTP.

## Entregável único

`docs/spikes/scraping-efetividade-audit.md`, com:

0. Resumo executivo (≤10 linhas): o que mais aumenta a captura e o que mais reduz custo.
1. a 5. Uma seção por investigação, com os achados (`arquivo:linha`), o desenho proposto, o custo (requisições/dia, queries ao Supabase, CPU/memória no Pi) e o risco para o ADR-0001/0002.
6. **Backlog priorizado** em tabela: item | impacto em captura | impacto em eficiência | esforço (P/M/G) | pré-requisito | **go / no-go / precisa de dado**. Cada item GO deve virar uma sugestão de spec (`specs/024-*`, `025-*`…) com título e critério de aceite. **Não crie as specs e não implemente nada.**
7. Lista de tudo que ficou **NÃO VERIFICADO** e como verificar.
