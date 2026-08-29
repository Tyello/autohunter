# Auditoria de índices — queries quentes (2026-08-29)

Tier: T3 (schema change em produção, múltiplas tabelas, 2 constraints únicas
faltando causando bug ativo de dados). Migration testada upgrade/downgrade/upgrade
contra o Supabase de produção via introspecção real (pg_indexes/pg_constraint) e
EXPLAIN (ANALYZE, BUFFERS).

## Achado crítico: alembic com 3 heads divergentes

`alembic heads` mostrava 3 pontas (`e2f3a4b5c6d7`, `p0_02_fipe_update_runs`,
`p1_notif_dq_partial`) e `alembic current` confirmava as 3 aplicadas em
produção. Isso indica que migrations foram aplicadas fora de ordem/por
branches diferentes em algum momento. Consequência prática: **duas
constraints que o código já pressupõe nunca existiram em produção**, mesmo
tendo migration própria já mergeada na árvore (ancestral das heads atuais).
A migration nova (`f4a8c1d3e7b2`) faz merge dos 3 heads em um só.

## REQ-001 — dedupe/upsert car_listings por (source, external_id)

**Código:** `app/repositories/car_listings_repo.py::insert_ignore_duplicates_return_ids`
usa `on_conflict_do_update(index_elements=["source", "external_id"])`.

**Antes:** nenhum índice único em `(source, external_id)` existia em produção
(só um índice não-único `car_listings_source_external_id_created_at_idx`).
Postgres exige um índice único exato para resolver o arbiter do `ON
CONFLICT` — sem ele, **toda chamada falhava** e caía silenciosamente no
fallback `_fallback_upsert_without_constraint` (`SELECT` + `INSERT`/`UPDATE`
linha a linha, sem bulk, sem atomicidade). Prova: 5 pares duplicados (10
linhas) da fonte `olx`, criados em segundos um do outro, encontrados em
produção — efeito direto da ausência de constraint.

**Depois:** `CREATE UNIQUE INDEX CONCURRENTLY uq_car_listings_source_external_id
ON car_listings (source, external_id)`. Testado em produção: `INSERT ...
ON CONFLICT (source, external_id) DO UPDATE ...` resolve sem erro agora
(antes: `there is no unique or exclusion constraint matching the on
conflict specification`). O bulk upsert volta a ser 1 statement em vez de N
round-trips.

**Custo antes/depois:** o `SELECT` do fallback já usava o índice existente
(0.135ms, `Index Scan` — plano bom), então o ganho não é de plano de
query, é de **arquitetura de chamada**: 1 `INSERT ... ON CONFLICT` bulk vs.
N `SELECT`+`INSERT`/`UPDATE` sequenciais por listing ingerido.

## REQ-002 — notifications_queue dedupe (wishlist_id, car_listing_id)

**Código:** `queue_notifications_for_matches` filtra
`Notification.wishlist_id == X, Notification.car_listing_id.in_(ids)`.

**Antes:** migration `31a3a2c240bd` (`uq_notifications_wishlist_listing`) é
ancestral das heads atuais na árvore de migrations, mas **não estava
aplicada** em produção (mesmo drift dos 3 heads). Só existiam índices
soltos em `wishlist_id` e `car_listing_id` separados — plano usava Bitmap
Scan em `car_listing_id` + Filter em `wishlist_id`.

**Depois:** `CREATE UNIQUE INDEX CONCURRENTLY
uq_notifications_wishlist_listing ON notifications (wishlist_id,
car_listing_id)`. Verificado: zero grupos duplicados com `wishlist_id`
não-nulo em produção antes de criar (linhas com `wishlist_id IS NULL` são
ignoradas por unicidade do Postgres, sem risco). Corrige tanto performance
quanto uma race condition real (nada impedia duas notifications para o
mesmo par sob concorrência).

Também restaurados (mesma migration ancestral ausente, `6bc6fd42271c`):
`ix_notifications_status_created_at`, `ix_notifications_user_status_created_at`,
`ix_notifications_reason` — usados por telas de admin/sender que filtram
por status/reason e não tinham índice em produção.

**Não alterado (já adequado):** `ix_notifications_delivery_queue_active`
(parcial, `WHERE status IN ('queued','processing')`) já cobre a fila de
pendentes do sender — é exatamente o índice parcial de status pendente que
o pedido original citava, e já existia em produção.

## REQ-003 — matching de listings ativas (wishlist_listing_activity)

**Código:** `weekly_wishlist_digest_service.py::_active_rows_for_wishlist`
filtra `wishlist_id == X, status == 'active', car_listing_id IS NOT NULL`,
join com `car_listings.is_sold == false`.

**Antes:** só existia índice em `wishlist_id` isolado (+ o índice único de
`(wishlist_id, listing_identity_key)`, que não ajuda esse filtro por
`status`). Plano: Index Scan em `wishlist_id`, filtro de `status`/`is_sold`
aplicado depois (`Filter`, não `Index Cond`).

**Depois:** `CREATE INDEX CONCURRENTLY ix_wishlist_activity_wishlist_status
ON wishlist_listing_activity (wishlist_id, status)`. `status` agora entra
no Index Cond.

## auction_lots e fipe_catalog_entries — sem full scan, sem ação

Ambos já têm cobertura composta adequada nos modelos e em produção:
`auction_lots`: `uq_auction_lots_source_external_id`,
`ix_auction_lots_source_status`, `ix_auction_lots_make_model_year`,
`ix_auction_lots_item_type_status`, `ix_auction_lots_city_state`.
`fipe_catalog_entries`: `uq_fipe_catalog_entries_identity`,
`ix_fipe_catalog_month_type`, `ix_fipe_catalog_brand_model_year`,
`ix_fipe_catalog_fipe_code`. EXPLAIN ANALYZE nas queries de filtro por
`source+status` e `reference_month+vehicle_type+brand` não mostrou full
scan. Observação secundária (fora do escopo pedido, não migrada): o
planner às vezes prefere `fipe_catalog_entries_reference_month_idx`
(coluna única) sobre o composto `ix_fipe_catalog_month_type` para filtros
por mês — índice redundante candidato a remoção futura, não crítico.

## Migration

`migrations/versions/f4a8c1d3e7b2_hot_query_index_coverage_audit.py` —
merge dos 3 heads divergentes + dedupe defensivo de `car_listings` (só
remove linhas duplicadas sem FK filha; grupos com filhos ficariam e
travariam a criação do índice único de propósito, sinalizando intervenção
manual) + 6 índices/constraints via `CREATE INDEX CONCURRENTLY` (fora de
transação, não bloqueia produção).

**Testado em produção (Supabase, leitura+escrita autorizada pelo
usuário):**
- `upgrade head`: aplicou limpo, incluindo a migration pendente
  `e2f3a4b5c6d7` que também não estava aplicada.
- Confirmado via `pg_constraint`/`pg_indexes`: todos os 6 objetos criados,
  0 grupos duplicados restantes em `car_listings`, `alembic_version` com 1
  head só.
- `ON CONFLICT (source, external_id)` testado com INSERT real (revertido
  via ROLLBACK): resolve sem erro.
- `downgrade` para um dos heads pai: remove os 6 índices/constraints
  limpo (dados deduplicados não são restaurados — irreversível por
  natureza, documentado no docstring da migration).
- Re-`upgrade head`: restaura estado final.
- `pytest tests/test_notifications_queue_service.py
  tests/test_fipe_on_demand_lookup_service.py`: 100% verde após as
  mudanças de modelo.

## Modelos atualizados (com migration correspondente)

- `app/models/car_listing.py`: `__table_args__` com
  `UniqueConstraint("source", "external_id", ...)` (antes não declarava
  nenhum índice/constraint).
- `app/models/notification.py`: `__table_args__` com a unique constraint e
  os 3 índices restaurados.
- `app/models/wishlist_listing_activity.py`: `Index("wishlist_id",
  "status")` adicionado ao `__table_args__` existente.
