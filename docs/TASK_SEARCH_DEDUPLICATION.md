# TASK — Deduplicação de buscas via chave canônica

> **Para:** Claude Code
> **Decisão de referência:** docs/adr/ADR-0001-search-deduplication.md (leia antes)
> **Repo:** autohunter — Python 3.13, SQLAlchemy, Supabase (Postgres remoto), Pi 4
> **Tipo:** mudança arquitetural no fluxo de scraping/matching
> **Risco:** ALTO de falso negativo silencioso (usuário deixar de receber alerta). A baseline dourada é obrigatória e inegociável.

---

## 0. Objetivo

Colapsar buscas idênticas de wishlists diferentes numa única raspagem por tick,
com fan-out dos resultados para todas as wishlists inscritas. O custo de scraping
deve passar a escalar pelo número de **buscas distintas**, não de usuários.

NÃO é construir do zero: o caminho wishlist-agnóstico já existe
(`scrape_ingest_match` com `wishlist is None` →
`match_listings_for_active_wishlists` via índice invertido). Esta tarefa
introduz a **chave canônica** que decide quais wishlists colapsam numa raspagem,
e roteia o tick recorrente por ela.

## 1. Leia primeiro

- docs/adr/ADR-0001-search-deduplication.md (contexto e decisão)
- app/scheduler/jobs.py — `scrape_ingest_match` (os dois modos), o loop do tick
- app/services/matching_service.py — `match_listings_for_active_wishlists`
- app/services/wishlist_tokens_service.py — índice invertido
- app/services/source_url_cursors_service.py — chave `(source, url)` já existente
- app/models/wishlist.py — campos `query`, `filters`, `is_active`
- como o `search_url` é construído a partir de uma wishlist (rastrear de onde vem
  o `search_url` passado a `scrape_ingest_match` no modo por-wishlist)

## 2. Pré-flight

- [ ] `git checkout -b feat/search-deduplication`
- [ ] Confirmar suíte verde antes de começar (`pytest`).

## 3. Baseline dourada (OBRIGATÓRIA, antes de mudar lógica)

O contrato a preservar: **para cada wishlist ativa, o conjunto de listings que ela
casa num tick não pode mudar** ao migrar do caminho por-wishlist para o canônico.

- [ ] Criar `tests/test_search_dedup_baseline.py` com fixture representativo:
  - várias wishlists ativas, incluindo **pares que devem colapsar** (mesma busca,
    fontes iguais) e **pares que NÃO devem colapsar** (mesma string mas filtros
    formadores de URL diferentes — ex.: faixa de preço/ano embutida na URL).
  - inclua wishlist legada sem `filters` relacionais.
- [ ] O teste roda o fluxo de matching/queue ATUAL e serializa
  `{wishlist_id -> set(listing_id)}` como golden.
- [ ] Confirmar verde com o código atual.

## 4. Canonicalização

- [ ] Implementar `canonical_search_key(wishlist) -> tuple[str, str]` (source, search_key).
  - A chave cobre **apenas** campos que alteram a URL/resultado da raspagem
    (modelo/termos de busca + filtros que entram na URL da fonte).
  - Filtros finos aplicados pós-scrape (cor, cidade, tipo de vendedor, faixas que
    NÃO entram na URL) **NÃO** entram na chave — eles continuam no fan-out por
    wishlist, onde já funcionam.
  - Determinística: normalizar caixa, ordem de tokens, espaços. Mesma entrada →
    mesma chave, sempre.
- [ ] Teste unitário dedicado da canonicalização: pares que devem/ não devem
  colidir, incluindo acentuação e variações de caixa.

> REGRA DE OURO: na dúvida entre colapsar ou não, **NÃO colapse**. Falso negativo
> (alerta perdido) é pior que uma raspagem redundante. É melhor a chave ser
> conservadora (menos colapso, correto) do que agressiva (mais colapso, arriscado).

## 5. Roteamento por busca canônica

- [ ] No tick recorrente: construir o **conjunto único** de
  `canonical_search_key` sobre todas as wishlists ativas.
- [ ] Scrapear cada busca canônica **uma vez** (reusar `source_url_cursors` para
  paginação/incremental, já keyed por `(source, url)`).
- [ ] Fan-out: casar o resultado contra todas as wishlists ativas via
  `match_listings_for_active_wishlists` (já eficiente pós-refactor) e enfileirar
  notificações por wishlist como hoje.
- [ ] Decisão sobre o caminho por-wishlist: **manter** apenas para ação sob
  demanda ("buscar agora" do usuário); removê-lo do tick recorrente. NÃO apagar a
  função — só deixar de chamá-la no agendamento recorrente.

## 6. Verificação (todos obrigatórios)

- [ ] Baseline dourada (passo 3) continua verde: mesmo `{wishlist_id -> set(listing_id)}`.
- [ ] `pytest` completo verde.
- [ ] Métrica de redução: instrumentar e logar `raspagens_por_tick` antes/depois
  no mesmo fixture (ex.: 10 wishlists "Civic Si" → 1 raspagem). Colar no PR.
- [ ] Confirmar que wishlists que NÃO devem colapsar continuam gerando raspagens
  separadas (anti-regressão do passo 4).

## 7. Guardrails

- A chave canônica é conservadora por padrão. Na dúvida, não colapsa.
- Escopo: canonicalização + roteamento do tick + testes. NÃO mexer no schema de
  dados, no índice parcial de notificações, nem no matcher (que já está pronto).
- Se descobrir que muitas wishlists embutem filtros na URL e por isso quase nada
  colapsa, PARE e reporte com números — a chave pode precisar separar URL-base de
  parâmetros, e isso é decisão de arquitetura (volta pro ADR).
- Não usar o caminho por-wishlist e o canônico ao mesmo tempo no tick (geraria
  notificação duplicada ou trabalho dobrado).

## 8. Entrega

PR em `feat/search-deduplication` com: resumo, prova da baseline dourada verde
(mesmos matches), os números de `raspagens_por_tick` antes/depois, e a lista de
quais pares de wishlist colapsaram e quais não (com o motivo). Reporte qualquer
caso onde a canonicalização foi ambígua.
