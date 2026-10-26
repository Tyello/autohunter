# Banco de dados — referência de tabelas e campos

> **Para agentes/IA:** leia este arquivo antes de criar/alterar model, migration, query SQL ou script que toque o banco. Os nomes de coluna abaixo são os reais; não assuma (ex.: `source_configs.is_enabled`, **não** `enabled`).

O bloco entre `BEGIN GENERATED` e `END GENERATED` é gerado dos models por `scripts/generate_db_schema_doc.py` (não edite à mão; rode o script). O texto fora do bloco é curado.

```bash
.venv/Scripts/python.exe scripts/generate_db_schema_doc.py          # regenera
.venv/Scripts/python.exe scripts/generate_db_schema_doc.py --check  # CI/teste: falha se desatualizado
```

`tests/test_database_schema_doc_up_to_date.py` falha se um model mudar sem regenerar este arquivo.

## Fatos verificados em produção (26/10/2026)

- PostgreSQL remoto. Código implantado no commit `aeded66`; `alembic_version` = `p2_run_id_fk_idx`, que é o head das migrations em `migrations/versions/`.
- Comparação das colunas de produção (`information_schema`) com os models: **sem divergência** de colunas ou nulabilidade nas 33 tabelas dos models.
- Tabelas em produção **sem model**: `alembic_version` (Alembic) e `apscheduler_jobs` (jobstore do APScheduler). Não mexa nelas à mão.
- Ordem de grandeza (linhas): `system_logs` ~89 mil, `car_listings` ~32 mil, `telemetry_events` ~15 mil, `source_runs` ~4,6 mil, `notifications` ~800, `scrape_jobs` ~315, `wishlists` 27, `users` 2.

## Convenções

- PKs são `UUID` (`uuid.uuid4`), exceto `app_kv.key` (texto). Ao colocar um id em JSON (`payload`, `tags`, logs), converta para `str`; `system_logs` já faz isso via `_json_safe`, mas qualquer outra coluna JSONB não.
- A maioria das tabelas herda `TimestampMixin` (`created_at`, `updated_at`, `timestamptz`, default aplicado pelo SQLAlchemy, não pelo banco).
- Colunas `JSONB` flexíveis (`source_configs.extra`, `app_kv.value`, `*.payload`) exigem validação e teste ao mudar o formato.
- Nenhuma tabela usa enum do Postgres: estados são `TEXT` com valores por convenção (lista abaixo).
- Tabelas protegidas contra `DELETE`/`TRUNCATE` por trigger (ver `docs/DB_GUARDRAILS.md`): `users`, `wishlists`, `wishlist_filters`, `wishlist_tokens`, `wishlist_tracked_listings`, `wishlist_listing_activity`, `notifications`, `account_members`, `user_digest_preferences`.

## Valores de estado (TEXT) observados

| Coluna | Valores no código/produção |
|---|---|
| `scrape_jobs.status` | `queued`, `running`, `done`, `failed` (produção hoje: só `done`) |
| `scrape_jobs.queue` | `browser` (1 worker serial, hard timeout 780 s), `http` (2 workers) |
| `scrape_jobs.result_status` | `success`, `blocked`, `error`, `skipped`, `not_ok:<status>` |
| `notifications.status` | `queued`, `processing`, `sent`, `failed`, `suppressed`, `discard` (produção: `sent`, `suppressed`) |
| `source_runs.kind` | `queue`, `scheduler` |
| `source_runs.status` | `success`, `error`, `blocked`, `skipped` |
| `source_states.last_status` | `success`, `skipped:disabled`, e demais status de run |
| `system_logs.level` | `debug`, `info`, `warn`, `error` (o código também aceita `warning`/`critical` na filtragem de stdout) |
| `car_listings.status` | `ativo` (default; o upsert sempre devolve a `ativo` ao reaparecer), `inativo` ("não vi mais", reversível; escrito por `listing_presence_service`), `suspeito` (reservado, nada escreve) |
| `car_listings.is_sold` | venda **confirmada pela source** (ex.: sites que mantêm o anúncio marcado como vendido). Semântica OR: nunca reverte. Hoje nenhum scraper preenche. Não usar para "sumiu da lista" |

### Inatividade de `car_listings` (presença por busca)

`listing_presence_service` marca `status='inativo'` aproveitando os scrapes: um anúncio ausente de `missing_runs` buscas **completas** seguidas da mesma busca (`last_seen_search_key`) vira `inativo`. Busca com página cheia (`found >= page_capacity`) ou vazia nunca conta como ausência. Config por source em `source_configs.extra.inactive_reconcile` (default `off`): `{"mode": "off|dry_run|on", "page_capacity": 40, "missing_runs": 3, "stale_days": 30}`. `dry_run` só conta/loga (`system_logs` eventos `presence_reconcile` / `presence_stale`). `stale_days` é a rede de segurança por `last_seen_at` aplicada ao fim de run bem-sucedido. Consumidores que ignoram `inativo`: `/buscar`, facets, backfill, digest semanal, tracking (`listing_is_unavailable`).

## `app_kv` — chaves conhecidas

Ponteiros e configs operacionais (JSONB). Padrões de chave no código:

- `auction_notification_settings` — config runtime das notificações de leilão (fallback em settings/env).
- `auction_last_dry_run_samples`, `auction_last_previewable_auction_sample` — amostras do dry-run de leilões.
- `weekly_wishlist_digest:last_run` — cursor do digest semanal.
- `ml_session_health` — saúde da sessão do Mercado Livre.
- `ops_alert:<key>`, `ops_alert:missing_admin_alert_chat` — throttle de alertas admin.
- `<CURSOR_KV_PREFIX><source>` — cursor de pacing por source (`source_execution_service.py`).
- `<prefixo>:<payment_id>` — idempotência do webhook Mercado Pago.

## Checklist antes de mexer no banco

1. Procure a tabela/coluna abaixo e confirme o nome real, tipo e nulabilidade.
2. Mudança de schema = model **+** migration Alembic (`migrations/versions/`) **+** regenerar este doc. Valide com `docs/ALEMBIC_POSTGRES_VALIDATION.md`.
3. Não remova coluna/tabela sem evidência de uso (`docs/SCHEMA_USAGE_AUDIT.md`, `scripts/schema_usage_audit.py`).
4. Nunca rode `DELETE`/`TRUNCATE` em tabela protegida sem o break-glass de `docs/DB_GUARDRAILS.md`.
5. Consultas em produção: somente leitura (`SET TRANSACTION READ ONLY`, apenas `SELECT`). As credenciais ficam em `.env` com permissão restrita; não imprima `DATABASE_URL`.
6. Tabelas quentes e grandes (`system_logs`, `telemetry_events`, `source_runs`, `car_listings`): filtre por `created_at` e use índice (ver `docs/DB_REVIEW.md`).

<!-- BEGIN GENERATED -->

Total de tabelas nos models: **33**.

## Índice

- **Usuarios, contas e planos:** [`users`](#users), [`accounts`](#accounts), [`account_members`](#account_members), [`plans`](#plans), [`subscriptions`](#subscriptions), [`user_digest_preferences`](#user_digest_preferences)
- **Buscas (wishlists) e rastreamento:** [`wishlists`](#wishlists), [`wishlist_filters`](#wishlist_filters), [`wishlist_tokens`](#wishlist_tokens), [`wishlist_tracked_listings`](#wishlist_tracked_listings), [`wishlist_listing_activity`](#wishlist_listing_activity)
- **Anuncios e notificacoes:** [`car_listings`](#car_listings), [`notifications`](#notifications)
- **Scraping: configuracao, estado e execucao:** [`source_configs`](#source_configs), [`source_states`](#source_states), [`source_runs`](#source_runs), [`source_url_cursors`](#source_url_cursors), [`scrape_jobs`](#scrape_jobs)
- **Leiloes:** [`auction_lots`](#auction_lots), [`auction_events`](#auction_events)
- **FIPE:** [`fipe_prices`](#fipe_prices), [`fipe_sync_runs`](#fipe_sync_runs), [`fipe_catalog_entries`](#fipe_catalog_entries), [`fipe_lookup_requests`](#fipe_lookup_requests), [`fipe_update_runs`](#fipe_update_runs)
- **Facebook:** [`fb_sessions`](#fb_sessions), [`fb_agent_sessions`](#fb_agent_sessions)
- **Observabilidade, admin e KV:** [`system_logs`](#system_logs), [`telemetry_events`](#telemetry_events), [`admin_deploy_audits`](#admin_deploy_audits), [`app_kv`](#app_kv), [`autopilot_findings`](#autopilot_findings), [`market_stats_cohorts`](#market_stats_cohorts)

## Usuarios, contas e planos

### `users`

`app.models.user.User`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não |  | PK |  |
| `telegram_chat_id` | BIGINT | não |  | UQ |  |
| `username` | TEXT | sim |  |  |  |
| `is_active` | BOOLEAN | não | `True` |  |  |
| `last_daily_limit_notice_at` | DATETIME | sim |  |  |  |
| `plan` | TEXT | não | `'free'` |  |  |
| `daily_limit_override` | INTEGER | sim |  |  |  |
| `account_id` | UUID | sim |  | FK → accounts.id (SET NULL) |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- UNIQUE `` (telegram_chat_id)

### `accounts`

`app.models.account.Account`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `type` | TEXT | não | `'personal'` |  | personal\|team |
| `name` | TEXT | sim |  |  |  |
| `is_active` | BOOLEAN | não | `True` |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

### `account_members`

`app.models.account_member.AccountMember`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `account_id` | UUID | não |  | FK → accounts.id (RESTRICT) |  |
| `user_id` | UUID | não |  | FK → users.id (RESTRICT) |  |
| `role` | TEXT | não | `'owner'` |  |  |

### `plans`

`app.models.plan.Plan`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `code` | TEXT | não |  | UQ | free\|premium |
| `name` | TEXT | não |  |  |  |
| `daily_alert_limit` | INTEGER | não |  |  |  |
| `max_wishlists` | INTEGER | não | `3` |  |  |
| `is_active` | BOOLEAN | não | `True` |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- UNIQUE `` (code)

### `subscriptions`

`app.models.subscription.Subscription`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `account_id` | UUID | não |  | FK → accounts.id (RESTRICT) |  |
| `plan_id` | UUID | não |  | FK → plans.id (RESTRICT) |  |
| `status` | TEXT | não | `'active'` |  |  |
| `daily_alert_limit_override` | INTEGER | sim |  |  |  |
| `starts_at` | DATETIME | não | server: `now()` |  | NOT NULL no banco -> precisa default no ORM (e proteção server-side) |
| `ends_at` | DATETIME | sim |  |  |  |
| `current_period_start` | DATETIME | sim |  |  |  |
| `current_period_end` | DATETIME | sim |  |  |  |
| `cancel_at_period_end` | BOOLEAN | não | server: `false` |  |  |
| `metadata` | JSON | sim |  |  |  |
| `source` | TEXT | não | `'manual'` |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

### `user_digest_preferences`

`app.models.user_digest_preference.UserDigestPreference`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `user_id` | UUID | não |  | FK → users.id, UQ |  |
| `weekly_digest_enabled` | BOOLEAN | não | `False` |  |  |
| `digest_days` | INTEGER | não | `7` |  |  |
| `digest_limit` | INTEGER | não | `10` |  |  |
| `last_digest_sent_at` | DATETIME | sim |  |  |  |
| `last_digest_previewed_at` | DATETIME | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- CHECK `ck_user_digest_preferences_days_range`: `digest_days >= 1 AND digest_days <= 30`
- CHECK `ck_user_digest_preferences_limit_range`: `digest_limit >= 1 AND digest_limit <= 20`
- UNIQUE `` (user_id)

## Buscas (wishlists) e rastreamento

### `wishlists`

`app.models.wishlist.Wishlist`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `user_id` | UUID | não |  | FK → users.id (RESTRICT) |  |
| `query` | TEXT | não |  |  |  |
| `is_active` | BOOLEAN | não | `True` |  |  |
| `include_auctions` | BOOLEAN | não | server: `false` |  |  |
| `deleted_at` | DATETIME | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

### `wishlist_filters`

`app.models.wishlist_filter.WishlistFilter`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `wishlist_id` | UUID | não |  | FK → wishlists.id (RESTRICT) |  |
| `is_active` | BOOLEAN | não | server: `true` |  |  |
| `field` | TEXT | não |  |  |  |
| `operator` | TEXT | não |  |  |  |
| `value` | TEXT | não |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- UNIQUE INDEX `uq_wishlist_filters_wishlist_field_op_value_active` (wishlist_id, field, operator, value)

### `wishlist_tokens`

`app.models.wishlist_token.WishlistToken`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `wishlist_id` | UUID | não |  | PK, FK → wishlists.id (RESTRICT) |  |
| `token` | TEXT | não |  | PK |  |
| `created_at` | DATETIME | não | server: `now()` |  |  |

### `wishlist_tracked_listings`

`app.models.wishlist_tracked_listing.WishlistTrackedListing` — User-selected listings tracked under a wishlist (max 3 rows per wishlist).

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `wishlist_id` | UUID | não |  | FK → wishlists.id (RESTRICT) |  |
| `car_listing_id` | UUID | sim |  | FK → car_listings.id (SET NULL) |  |
| `is_active` | BOOLEAN | não | server: `true` |  |  |
| `slot` | INTEGER | não |  |  |  |
| `initial_price` | NUMERIC(12, 2) | sim |  |  |  |
| `last_observed_price` | NUMERIC(12, 2) | sim |  |  |  |
| `last_price_change_amount` | NUMERIC(12, 2) | sim |  |  |  |
| `last_price_change_pct` | NUMERIC(7, 4) | sim |  |  |  |
| `last_price_change_direction` | TEXT | sim |  |  |  |
| `last_price_change_at` | DATETIME | sim |  |  |  |
| `last_seen_at` | DATETIME | sim |  |  |  |
| `listing_status` | TEXT | sim |  |  |  |
| `price_drop_alert_enabled` | BOOLEAN | não | `False` |  |  |
| `last_price_drop_alert_at` | DATETIME | sim |  |  |  |
| `last_price_drop_alert_price` | NUMERIC(12, 2) | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- CHECK `ck_wishlist_tracked_listing_slot_range`: `slot >= 1 AND slot <= 3`
- UNIQUE INDEX `uq_wishlist_tracked_listing_pair_active` (wishlist_id, car_listing_id)
- UNIQUE INDEX `uq_wishlist_tracked_listing_slot_active` (wishlist_id, slot)

### `wishlist_listing_activity`

`app.models.wishlist_listing_activity.WishlistListingActivity` — Persistent activity state for listing lifecycle per wishlist.

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `wishlist_id` | UUID | não |  | FK → wishlists.id (RESTRICT) |  |
| `car_listing_id` | UUID | sim |  | FK → car_listings.id (SET NULL) |  |
| `last_valid_run_id` | UUID | sim |  | FK → source_runs.id (SET NULL) |  |
| `listing_identity_key` | TEXT | não |  |  |  |
| `source_name` | TEXT | não |  |  |  |
| `source_listing_id` | TEXT | sim |  |  |  |
| `listing_url` | TEXT | sim |  |  |  |
| `status` | TEXT | não | `'active'` |  | active\|inactive |
| `first_seen_at` | DATETIME | não |  |  |  |
| `last_seen_at` | DATETIME | não |  |  |  |
| `missing_runs_count` | INTEGER | não | `0` |  |  |
| `inactive_at` | DATETIME | sim |  |  |  |
| `inactive_reason` | TEXT | sim |  |  |  |
| `reactivated_at` | DATETIME | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- UNIQUE `uq_wishlist_listing_activity_wishlist_identity` (wishlist_id, listing_identity_key)
- INDEX `ix_wishlist_activity_wishlist_status` (wishlist_id, status)

## Anuncios e notificacoes

### `car_listings`

`app.models.car_listing.CarListing` — Normalized automotive listing.

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `source` | TEXT | não |  |  | Dedup |
| `external_id` | TEXT | não |  |  |  |
| `title` | TEXT | sim |  |  | Core fields |
| `url` | TEXT | não |  |  |  |
| `thumbnail_url` | TEXT | sim |  |  |  |
| `price` | NUMERIC(12, 2) | sim |  |  |  |
| `currency` | TEXT | não | `'BRL'` |  |  |
| `location` | TEXT | sim |  |  |  |
| `extras` | JSONB | não | callable |  | Extensible / debug |
| `raw_payload` | JSONB | sim |  |  |  |
| `listing_type` | TEXT | não | `'marketplace'` |  |  |
| `extractor_version` | TEXT | sim |  |  |  |
| `year` | INTEGER | sim |  |  | Promoted common fields |
| `mileage_km` | INTEGER | sim |  |  |  |
| `fuel_type` | TEXT | sim |  |  |  |
| `transmission` | TEXT | sim |  |  |  |
| `make` | TEXT | sim |  |  |  |
| `model` | TEXT | sim |  |  |  |
| `version` | TEXT | sim |  |  |  |
| `seller_type` | TEXT | sim |  |  |  |
| `city` | TEXT | sim |  |  |  |
| `state` | TEXT | sim |  |  |  |
| `color` | TEXT | sim |  |  |  |
| `doors` | INTEGER | sim |  |  |  |
| `body_type` | TEXT | sim |  |  |  |
| `cross_source_fingerprint` | TEXT | sim |  |  |  |
| `is_sold` | BOOLEAN | não | `False` |  | Marketplace lifecycle |
| `sold_at` | DATETIME | sim |  |  |  |
| `status` | TEXT | não | server: `ativo` |  |  |
| `last_seen_at` | DATETIME | não | server: `CURRENT_TIMESTAMP` |  |  |
| `last_seen_search_key` | TEXT | sim |  |  | Presenca por busca (listing_presence_service): ultima busca/grupo em que o anuncio apareceu e quantas buscas completas seguidas dessa mesma busca nao o trouxeram. |
| `missing_runs_count` | INTEGER | não | server: `0` |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- CHECK `check_status_valid`: `status IN ('ativo','suspeito','inativo')`
- UNIQUE `uq_car_listings_source_external_id` (source, external_id)
- INDEX `ix_car_listings_source_search_key` (source, last_seen_search_key)

### `notifications`

`app.models.notification.Notification`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `user_id` | UUID | não |  | FK → users.id (RESTRICT) |  |
| `wishlist_id` | UUID | sim |  | FK → wishlists.id (SET NULL) |  |
| `car_listing_id` | UUID | não |  | FK → car_listings.id (RESTRICT) |  |
| `status` | TEXT | não | `'queued'` |  | queued\|processing\|sent\|failed\|suppressed\|discarded |
| `sent_at` | DATETIME | sim |  |  |  |
| `next_attempt_at` | DATETIME | sim |  |  |  |
| `processing_started_at` | DATETIME | sim |  |  |  |
| `processing_owner` | TEXT | sim |  |  |  |
| `attempts` | INTEGER | não | `0` |  |  |
| `max_attempts` | INTEGER | não | `3` |  |  |
| `reason` | TEXT | sim |  |  | Motivo curto (ex: daily_limit_reached, no_chat_id, telegram_error) |
| `error_message` | TEXT | sim |  |  | Mensagem detalhada (stacktrace/erro do provider etc.) |
| `score_v2` | INTEGER | sim |  |  | Score vNext (v2) persistido por notificação (wishlist_id + car_listing_id) |
| `score_breakdown` | JSONB | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- UNIQUE `uq_notifications_wishlist_listing_reason_score` (wishlist_id, car_listing_id, reason, score_v2)
- INDEX `ix_notifications_reason` (reason)
- INDEX `ix_notifications_status_created_at` (status, created_at)
- INDEX `ix_notifications_user_status_created_at` (user_id, status, created_at)

## Scraping: configuracao, estado e execucao

### `source_configs`

`app.models.source_config.SourceConfig` — Configuração operacional por fonte.

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `source` | TEXT | não |  | UQ |  |
| `source_type` | TEXT | não | `'classified'` |  |  |
| `user_eligible` | BOOLEAN | não | `False` |  |  |
| `admin_only` | BOOLEAN | não | `False` |  |  |
| `status` | TEXT | sim |  |  |  |
| `is_enabled` | BOOLEAN | não | `True` |  |  |
| `sched_minutes` | INTEGER | não | `60` |  |  |
| `cooldown_minutes` | INTEGER | não | `0` |  |  |
| `rate_limit_seconds` | INTEGER | não | `0` |  |  |
| `proxy_server` | TEXT | sim |  |  |  |
| `browser_fallback_enabled` | BOOLEAN | não | `False` |  | Browser/híbrido |
| `force_browser` | BOOLEAN | não | `False` |  |  |
| `extra` | JSONB | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- UNIQUE `` (source)

### `source_states`

`app.models.source_state.SourceState` — Estado operacional de uma fonte (backoff / saúde).

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `source` | TEXT | não |  | UQ |  |
| `next_allowed_at` | DATETIME | sim |  |  |  |
| `last_run_at` | DATETIME | sim |  |  |  |
| `last_effective_run_at` | DATETIME | sim |  |  | Última execução "efetiva" (quando houve scrape de fato). Útil para schedule dinâmico por DB (o tick pode acontecer, mas não necessariamente executa). |
| `consecutive_blocks` | INTEGER | não | `0` |  |  |
| `consecutive_failures` | INTEGER | não | `0` |  |  |
| `last_status` | TEXT | sim |  |  | success\|blocked\|error\|skipped |
| `last_error` | TEXT | sim |  |  |  |
| `last_payload` | JSONB | sim |  |  |  |
| `last_admin_alert_at` | DATETIME | sim |  |  | Admin alerts (throttle) |
| `last_admin_alert_status` | TEXT | sim |  |  |  |
| `last_admin_alert_error_hash` | TEXT | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- UNIQUE `` (source)

### `source_runs`

`app.models.source_run.SourceRun` — Métricas por execução (uma linha por run).

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `source` | TEXT | não |  |  |  |
| `kind` | TEXT | não |  |  | scheduler\|manual |
| `query` | TEXT | sim |  |  |  |
| `url` | TEXT | sim |  |  |  |
| `status` | TEXT | não |  |  | success\|blocked\|error\|skipped |
| `http_status` | INTEGER | sim |  |  |  |
| `duration_ms` | INTEGER | sim |  |  |  |
| `groups` | INTEGER | sim |  |  | execution shape |
| `wishlists` | INTEGER | sim |  |  |  |
| `items_found` | INTEGER | sim |  |  |  |
| `items_ingested` | INTEGER | sim |  |  |  |
| `items_matched` | INTEGER | sim |  |  |  |
| `notifications_queued` | INTEGER | sim |  |  |  |
| `proxy_server` | TEXT | sim |  |  | runtime config snapshot (optional) |
| `browser_fallback_enabled` | BOOLEAN | sim |  |  |  |
| `force_browser` | BOOLEAN | sim |  |  |  |
| `error` | TEXT | sim |  |  |  |
| `payload` | JSONB | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

### `source_url_cursors`

`app.models.source_url_cursor.SourceUrlCursor` — Per-(source,url) cursor for incremental scraping.

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `source` | TEXT | não |  |  |  |
| `url` | TEXT | não |  |  |  |
| `last_external_id` | TEXT | sim |  |  |  |
| `last_seen_at` | DATETIME | sim |  |  |  |
| `last_checked_at` | DATETIME | sim |  |  |  |
| `runs` | INTEGER | não | `0` |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

### `scrape_jobs`

`app.models.scrape_job.ScrapeJob` — Job persistente para execuções de scraping (fila).

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `source` | TEXT | não |  |  |  |
| `queue` | TEXT | não | `'browser'` |  |  |
| `run_at` | DATETIME | não |  |  | Agendamento |
| `priority` | INTEGER | não | `0` |  |  |
| `status` | TEXT | não | `'queued'` |  | Execução |
| `attempt` | INTEGER | não | `0` |  |  |
| `max_attempts` | INTEGER | não | `3` |  |  |
| `lock_owner` | TEXT | sim |  |  |  |
| `locked_at` | DATETIME | sim |  |  |  |
| `started_at` | DATETIME | sim |  |  |  |
| `finished_at` | DATETIME | sim |  |  |  |
| `duration_ms` | INTEGER | sim |  |  |  |
| `result_status` | TEXT | sim |  |  | Resultado |
| `result_payload` | JSONB | sim |  |  |  |
| `error` | TEXT | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

## Leiloes

### `auction_lots`

`app.models.auction_lot.AuctionLot`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `event_id` | UUID | sim |  | FK → auction_events.id (SET NULL) |  |
| `source` | TEXT | não |  |  |  |
| `external_id` | TEXT | não |  |  |  |
| `lot_number` | TEXT | sim |  |  |  |
| `title` | TEXT | sim |  |  |  |
| `description` | TEXT | sim |  |  |  |
| `url` | TEXT | sim |  |  |  |
| `thumbnail_url` | TEXT | sim |  |  |  |
| `item_type` | TEXT | não | `'other'` |  |  |
| `make` | TEXT | sim |  |  |  |
| `model` | TEXT | sim |  |  |  |
| `version` | TEXT | sim |  |  |  |
| `year` | INTEGER | sim |  |  |  |
| `mileage_km` | INTEGER | sim |  |  |  |
| `fuel_type` | TEXT | sim |  |  |  |
| `transmission` | TEXT | sim |  |  |  |
| `color` | TEXT | sim |  |  |  |
| `city` | TEXT | sim |  |  |  |
| `state` | TEXT | sim |  |  |  |
| `location` | TEXT | sim |  |  |  |
| `initial_bid` | NUMERIC(14, 2) | sim |  |  |  |
| `current_bid` | NUMERIC(14, 2) | sim |  |  |  |
| `bid_increment` | NUMERIC(14, 2) | sim |  |  |  |
| `total_bids` | INTEGER | sim |  |  |  |
| `status` | TEXT | não | `'unknown'` |  |  |
| `auction_start_at` | DATETIME | sim |  |  |  |
| `auction_end_at` | DATETIME | sim |  |  |  |
| `condition` | TEXT | sim |  |  |  |
| `document_type` | TEXT | sim |  |  |  |
| `condition_notes` | TEXT | sim |  |  |  |
| `has_documentation` | BOOLEAN | sim |  |  |  |
| `has_debts` | BOOLEAN | sim |  |  |  |
| `image_count` | INTEGER | sim |  |  |  |
| `images` | ARRAY | sim |  |  |  |
| `extras` | JSONB | sim |  |  |  |
| `raw_payload` | JSONB | sim |  |  |  |
| `first_seen_at` | DATETIME | não | callable |  |  |
| `last_seen_at` | DATETIME | não | callable |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- INDEX `ix_auction_lots_auction_end_at` (auction_end_at)
- INDEX `ix_auction_lots_city_state` (city, state)
- INDEX `ix_auction_lots_item_type_status` (item_type, status)
- INDEX `ix_auction_lots_make_model_year` (make, model, year)
- INDEX `ix_auction_lots_source_status` (source, status)
- UNIQUE INDEX `uq_auction_lots_source_external_id` (source, external_id)

### `auction_events`

`app.models.auction_event.AuctionEvent`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `source` | TEXT | não |  |  |  |
| `external_id` | TEXT | não |  |  |  |
| `title` | TEXT | sim |  |  |  |
| `url` | TEXT | sim |  |  |  |
| `event_date` | DATETIME | sim |  |  |  |
| `status` | TEXT | não | `'unknown'` |  |  |
| `city` | TEXT | sim |  |  |  |
| `state` | TEXT | sim |  |  |  |
| `auction_type` | TEXT | sim |  |  |  |
| `modality` | TEXT | sim |  |  |  |
| `auctioneer` | TEXT | sim |  |  |  |
| `organizer` | TEXT | sim |  |  |  |
| `total_lots` | INTEGER | sim |  |  |  |
| `vehicle_lots` | INTEGER | sim |  |  |  |
| `extras` | JSONB | sim |  |  |  |
| `raw_payload` | JSONB | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- INDEX `ix_auction_events_source_status` (source, status)
- UNIQUE INDEX `uq_auction_events_source_external_id` (source, external_id)

## FIPE

### `fipe_prices`

`app.models.fipe_price.FipePrice`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK | PK |
| `vehicle_key` | TEXT | não |  |  | Identificador simples do veículo no MVP (ex: "Honda Civic 2019 Touring") |
| `fipe_price` | NUMERIC(12, 2) | não |  |  | Valor FIPE |
| `currency` | TEXT | não | `'BRL'` |  |  |
| `reference_month` | TEXT | não |  |  | Competência (ex: "2026-01") |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- UNIQUE `uq_fipe_vehicle_month` (vehicle_key, reference_month)

### `fipe_sync_runs`

`app.models.fipe_sync_run.FipeSyncRun`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `reference_month` | TEXT | não |  |  |  |
| `source` | TEXT | não |  |  |  |
| `status` | TEXT | não | `'pending'` |  |  |
| `started_at` | DATETIME | sim |  |  |  |
| `finished_at` | DATETIME | sim |  |  |  |
| `rows_seen` | INTEGER | não | `0` |  |  |
| `rows_inserted` | INTEGER | não | `0` |  |  |
| `rows_updated` | INTEGER | não | `0` |  |  |
| `error` | TEXT | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- CHECK `ck_fipe_sync_runs_status`: `status IN ('pending','running','completed','failed')`

### `fipe_catalog_entries`

`app.models.fipe_catalog_entry.FipeCatalogEntry`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `reference_month` | TEXT | não |  |  |  |
| `vehicle_type` | TEXT | não | `'car'` |  |  |
| `brand_code` | TEXT | sim |  |  |  |
| `brand_name` | TEXT | sim |  |  |  |
| `model_code` | TEXT | sim |  |  |  |
| `model_name` | TEXT | não |  |  |  |
| `year_code` | TEXT | sim |  |  |  |
| `model_year` | INTEGER | sim |  |  |  |
| `fuel` | TEXT | sim |  |  |  |
| `fipe_code` | TEXT | sim |  |  |  |
| `identity_key` | TEXT | não |  |  |  |
| `price` | NUMERIC(12, 2) | não |  |  |  |
| `currency` | TEXT | não | `'BRL'` |  |  |
| `raw_payload` | JSONB | sim |  |  |  |
| `source` | TEXT | não |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- UNIQUE `uq_fipe_catalog_entries_identity` (reference_month, vehicle_type, source, identity_key)
- INDEX `ix_fipe_catalog_brand_model_year` (brand_name, model_name, model_year)
- INDEX `ix_fipe_catalog_fipe_code` (fipe_code)
- INDEX `ix_fipe_catalog_month_type` (reference_month, vehicle_type)

### `fipe_lookup_requests`

`app.models.fipe_lookup_request.FipeLookupRequest`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `wishlist_id` | UUID | não |  | FK → wishlists.id (RESTRICT) |  |
| `status` | TEXT | não | `'pending'` |  |  |
| `attempts` | INTEGER | não | `0` |  |  |
| `last_error` | TEXT | sim |  |  |  |
| `processed_at` | DATETIME | sim |  |  |  |
| `listing_make` | TEXT | sim |  |  |  |
| `listing_model` | TEXT | sim |  |  |  |
| `target_year` | INTEGER | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- CHECK `ck_fipe_lookup_requests_status`: `status IN ('pending','processing','done','skipped','failed')`
- INDEX `ix_fipe_lookup_requests_status_created` (status, created_at)

### `fipe_update_runs`

`app.models.fipe_update_run.FipeUpdateRun`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `started_at` | DATETIME | não |  |  |  |
| `finished_at` | DATETIME | sim |  |  |  |
| `status` | TEXT | não | `'running'` |  |  |
| `updated_rows` | INTEGER | não | `0` |  |  |
| `duration_ms` | INTEGER | sim |  |  |  |
| `error_message` | TEXT | sim |  |  |  |
| `reference_month` | TEXT | sim |  |  |  |
| `input_uri` | TEXT | sim |  |  |  |
| `lock_key` | TEXT | não | `'monthly_fipe_update'` |  |  |
| `payload` | JSONB | sim |  |  |  |

Constraints e índices:

- CHECK `ck_fipe_update_runs_status`: `status IN ('running','completed','failed','skipped')`
- INDEX `ix_fipe_update_runs_lock_status` (lock_key, status)
- INDEX `ix_fipe_update_runs_started_at` (started_at)
- INDEX `ix_fipe_update_runs_status_started` (status, started_at)

## Facebook

### `fb_sessions`

`app.models.fb_session.FBSession`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `user_id` | TEXT | não |  | UQ |  |
| `pairing_code` | TEXT | sim |  |  |  |
| `pairing_expires_at` | DATETIME | sim |  |  |  |
| `pairing_used_at` | DATETIME | sim |  |  |  |
| `status` | TEXT | não | `'PENDING_AUTH'` |  |  |
| `profile_dir` | TEXT | não |  |  |  |
| `session_validated_at` | DATETIME | sim |  |  |  |
| `last_check_at` | DATETIME | sim |  |  |  |
| `last_ok_at` | DATETIME | sim |  |  |  |
| `last_error_kind` | TEXT | sim |  |  |  |
| `last_error_message` | TEXT | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- INDEX `ix_fb_sessions_pairing_code` (pairing_code)
- INDEX `ix_fb_sessions_status` (status)
- UNIQUE INDEX `ix_fb_sessions_user_id` (user_id)

### `fb_agent_sessions`

`app.models.fb_agent_session.FBAgentSession`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `user_id` | TEXT | não |  | UQ |  |
| `pairing_code` | VARCHAR(16) | sim |  |  |  |
| `pairing_expires_at` | DATETIME | sim |  |  |  |
| `pairing_used_at` | DATETIME | sim |  |  |  |
| `status` | VARCHAR(32) | não | `'PENDING_AGENT'` |  |  |
| `agent_id` | VARCHAR(64) | sim |  |  |  |
| `agent_version` | VARCHAR(32) | sim |  |  |  |
| `last_seen_at` | DATETIME | sim |  |  |  |
| `last_check_at` | DATETIME | sim |  |  |  |
| `last_ok_at` | DATETIME | sim |  |  |  |
| `last_error_kind` | VARCHAR(32) | sim |  |  |  |
| `last_error_message` | VARCHAR(256) | sim |  |  |  |
| `action_hint` | VARCHAR(128) | sim |  |  |  |
| `bootstrap_token` | VARCHAR(128) | sim |  |  |  |
| `bootstrap_token_expires_at` | DATETIME | sim |  |  |  |
| `bootstrap_token_used_at` | DATETIME | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- INDEX `ix_fb_agent_sessions_bootstrap_token` (bootstrap_token)
- INDEX `ix_fb_agent_sessions_pairing_code` (pairing_code)
- INDEX `ix_fb_agent_sessions_status` (status)
- UNIQUE INDEX `ix_fb_agent_sessions_user_id` (user_id)

## Observabilidade, admin e KV

### `system_logs`

`app.models.system_log.SystemLog`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `level` | TEXT | não | `'info'` |  | info\|warn\|error |
| `component` | TEXT | não |  |  | ex: "scheduler", "scraper_mercadolivre", "scraper_olx", "bot" |
| `message` | TEXT | não |  |  | short label for humans (high-volume) |
| `source` | TEXT | sim |  |  | Optional structured fields (to power autopilot/agents without parsing JSON) e.g. 'olx', 'webmotors' |
| `run_id` | UUID | sim |  | FK → source_runs.id (SET NULL) | Optional link to a high-level source_runs row |
| `event_type` | TEXT | sim |  |  | machine-readable category, e.g. 'http_blocked', 'parse_failed', 'pipeline_summary' |
| `fingerprint` | TEXT | sim |  |  | stable dedupe key for the same underlying issue/signal |
| `tags` | ARRAY | sim |  |  |  |
| `payload` | JSONB | sim |  |  | payload livre para debug (jsonb) |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

### `telemetry_events`

`app.models.telemetry_event.TelemetryEvent` — High-signal, structured events for autopilot/agents.

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `level` | TEXT | não | `'info'` |  | info\|warn\|error |
| `source` | TEXT | sim |  |  | e.g. 'olx', 'webmotors' |
| `run_id` | UUID | sim |  | FK → source_runs.id (SET NULL) | optional link to a high-level source_runs row |
| `wishlist_id` | UUID | sim |  | FK → wishlists.id (SET NULL) |  |
| `user_id` | UUID | sim |  | FK → users.id (SET NULL) |  |
| `account_id` | UUID | sim |  | FK → accounts.id (SET NULL) |  |
| `event_type` | TEXT | não |  |  | machine-readable category, e.g. 'http_blocked', 'parse_failed', 'pipeline_summary' |
| `message` | TEXT | sim |  |  | human-readable short text (optional) |
| `fingerprint` | TEXT | não |  |  | stable dedupe key for the same underlying issue/signal |
| `tags` | ARRAY | sim |  |  |  |
| `evidence` | JSONB | sim |  |  | minimal evidence for debugging (jsonb) |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

### `admin_deploy_audits`

`app.models.admin_deploy_audit.AdminDeployAudit`

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `operation_id` | TEXT | não |  | UQ |  |
| `requested_by_tg_user_id` | BIGINT | sim |  |  |  |
| `requested_by_username` | TEXT | sim |  |  |  |
| `chat_id` | BIGINT | não |  |  |  |
| `requested_at` | DATETIME | não |  |  |  |
| `confirmed_at` | DATETIME | sim |  |  |  |
| `started_at` | DATETIME | sim |  |  |  |
| `finished_at` | DATETIME | sim |  |  |  |
| `expires_at` | DATETIME | sim |  |  |  |
| `status` | TEXT | não |  |  |  |
| `branch` | TEXT | sim |  |  |  |
| `before_commit` | TEXT | sim |  |  |  |
| `after_commit` | TEXT | sim |  |  |  |
| `services_json` | JSON | sim |  |  |  |
| `summary` | TEXT | sim |  |  |  |
| `output_tail` | TEXT | sim |  |  |  |
| `error_type` | TEXT | sim |  |  |  |
| `error_message` | TEXT | sim |  |  |  |

Constraints e índices:

- UNIQUE INDEX `ix_admin_deploy_audits_operation_id` (operation_id)
- INDEX `ix_admin_deploy_audits_status` (status)

### `app_kv`

`app.models.app_kv.AppKV` — Key/Value simples (JSONB) para ponteiros e configs operacionais.

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `key` | TEXT | não |  | PK |  |
| `value` | JSONB | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

### `autopilot_findings`

`app.models.autopilot_finding.AutopilotFinding` — Sinais detectados automaticamente a partir de SourceRuns/SystemLogs.

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `id` | UUID | não | callable | PK |  |
| `status` | TEXT | não | `'open'` |  | open\|closed |
| `kind` | TEXT | não |  |  | blocked_spike\|error_spike\|found_drop\|log_error_burst\|... |
| `source` | TEXT | sim |  |  | fonte relacionada (quando aplicável) |
| `fingerprint` | TEXT | não |  | UQ | dedupe key (sha1 etc) |
| `title` | TEXT | não |  |  |  |
| `severity` | TEXT | não | `'warn'` |  | info\|warn\|error |
| `first_seen_at` | DATETIME | não |  |  |  |
| `last_seen_at` | DATETIME | não |  |  |  |
| `hit_count` | INTEGER | não | `0` |  |  |
| `last_alert_at` | DATETIME | sim |  |  |  |
| `evidence` | JSONB | sim |  |  |  |
| `suggested_actions` | TEXT | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

Constraints e índices:

- UNIQUE `` (fingerprint)

### `market_stats_cohorts`

`app.models.market_stats.MarketStatsCohort` — Daily market stats by cohort (make+model+year).

| Coluna | Tipo | Null | Default | Chave | Notas |
|---|---|---|---|---|---|
| `make` | TEXT | não |  | PK |  |
| `model` | TEXT | não |  | PK |  |
| `year` | INTEGER | não |  | PK |  |
| `median_price` | NUMERIC(12, 2) | não |  |  |  |
| `p25_price` | NUMERIC(12, 2) | sim |  |  |  |
| `p75_price` | NUMERIC(12, 2) | sim |  |  |  |
| `sample_size` | INTEGER | não | `0` |  |  |
| `computed_at` | DATETIME | sim |  |  |  |
| `created_at` | DATETIME | não | callable |  |  |
| `updated_at` | DATETIME | não | callable |  |  |

<!-- END GENERATED -->

## Relações principais (resumo)

`users → wishlists → wishlist_filters/wishlist_tokens/wishlist_tracked_listings` · `wishlists + car_listings → notifications` · `source_configs/source_states` (1 linha por source) · `scrape_jobs` (fila) → `source_runs` (execução) → `system_logs.run_id` · `auction_lots` (leilões, fluxo separado de `car_listings`).
