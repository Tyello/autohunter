# Schema Usage Audit

Relatório gerado automaticamente por `scripts/schema_usage_audit.py`.

## Inventário
- Models SQLAlchemy analisados: **28**
- Migrations Alembic analisadas: **58**

## Inventário do banco real

Tabelas reais validadas no PostgreSQL de produção:

- `account_members`
- `accounts`
- `admin_deploy_audits`
- `alembic_version`
- `app_kv`
- `autopilot_findings`
- `car_listings`
- `fb_agent_sessions`
- `fb_sessions`
- `fipe_prices`
- `market_stats_cohorts`
- `notifications`
- `plans`
- `scrape_jobs`
- `source_configs`
- `source_runs`
- `source_states`
- `source_url_cursors`
- `subscriptions`
- `system_logs`
- `telemetry_events`
- `users`
- `wishlist_filters`
- `wishlist_listing_activity`
- `wishlist_tokens`
- `wishlist_tracked_listings`
- `wishlists`

## Features futuras mantidas no roadmap

- Facebook Marketplace/Auth:
  - `fb_sessions`
  - `fb_agent_sessions`
- FIPE e inteligência de preço:
  - `fipe_prices`
  - `market_stats_cohorts`
- Admin Deploy Audit:
  - `admin_deploy_audits`
- Autopilot:
  - `autopilot_findings`
- Leilões/oportunidades especiais:
  - `auction_events`
  - `auction_lots`
  - `auction_lot_service`

## Não remover agora

- Campos ricos de `car_listings` devem ser mantidos para filtros avançados.
- `fipe_prices` e `market_stats_cohorts` devem ser mantidos para inteligência de preço.
- `admin_deploy_audits` deve ser mantido porque o deploy via Telegram é usado diariamente.
- `autopilot_findings` deve ser mantido porque o Autopilot gera digest diário e será evoluído.
- `fb_sessions` e `fb_agent_sessions` devem ser mantidos como investigação futura, mas fora do piloto.
- `auction_*` deve ficar como roadmap futuro, não como runtime ativo.

## Candidatos reais de saneamento imediato

- Nenhum `DROP` recomendado nesta etapa.
- Classificar `auction_*` apenas como feature futura sem tabela real no banco atual.
- Sugerir PR futura para isolar/remover imports runtime de `auction_*` se estiverem no metadata principal e gerando confusão.

## Uso por tabela/coluna
### `account_members` (AccountMember)
- Model: `app/models/account_member.py`
- Menções em migrations: 16

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `account_id` | `READ_ACTIVE` | hits=80; read=11; write=13; ops=14; idx=4 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `role` | `READ_ACTIVE` | hits=116; read=15; write=6; ops=10; idx=2 | ALTO |
| `user_id` | `READ_ACTIVE` | hits=419; read=47; write=53; ops=38; idx=7 | ALTO |

### `accounts` (Account)
- Model: `app/models/account.py`
- Menções em migrations: 22

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `is_active` | `READ_ACTIVE` | hits=174; read=33; write=45; ops=19; idx=4 | ALTO |
| `name` | `READ_ACTIVE` | hits=864; read=81; write=104; ops=87; idx=29 | ALTO |
| `type` | `READ_ACTIVE` | hits=961; read=90; write=58; ops=106; idx=8 | ALTO |

### `admin_deploy_audits` (AdminDeployAudit)
- Model: `app/models/admin_deploy_audit.py`
- Menções em migrations: 14

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `after_commit` | `READ_ACTIVE` | hits=10; read=3; write=1; ops=10; idx=1 | ALTO |
| `before_commit` | `READ_ACTIVE` | hits=13; read=3; write=2; ops=13; idx=1 | ALTO |
| `branch` | `READ_ACTIVE` | hits=42; read=3; write=2; ops=42; idx=1 | ALTO |
| `chat_id` | `READ_ACTIVE` | hits=340; read=34; write=53; ops=112; idx=3 | ALTO |
| `confirmed_at` | `READ_ACTIVE` | hits=3; read=2; write=1; ops=3; idx=1 | ALTO |
| `error_message` | `READ_ACTIVE` | hits=78; read=12; write=7; ops=33; idx=4 | ALTO |
| `error_type` | `READ_ACTIVE` | hits=43; read=3; write=1; ops=41; idx=1 | ALTO |
| `expires_at` | `READ_ACTIVE` | hits=32; read=7; write=1; ops=5; idx=3 | ALTO |
| `finished_at` | `READ_ACTIVE` | hits=16; read=4; write=2; ops=12; idx=2 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `operation_id` | `READ_ACTIVE` | hits=51; read=3; write=2; ops=51; idx=1 | ALTO |
| `output_tail` | `READ_ACTIVE` | hits=11; read=3; write=0; ops=11; idx=1 | ALTO |
| `requested_at` | `READ_ACTIVE` | hits=8; read=3; write=2; ops=8; idx=1 | ALTO |
| `requested_by_tg_user_id` | `READ_ACTIVE` | hits=6; read=2; write=2; ops=6; idx=1 | ALTO |
| `requested_by_username` | `READ_ACTIVE` | hits=3; read=2; write=2; ops=3; idx=1 | ALTO |
| `services_json` | `READ_ACTIVE` | hits=2; read=1; write=0; ops=2; idx=1 | ALTO |
| `started_at` | `READ_ACTIVE` | hits=55; read=11; write=7; ops=18; idx=3 | ALTO |
| `status` | `READ_ACTIVE` | hits=1069; read=97; write=67; ops=247; idx=13 | ALTO |
| `summary` | `READ_ACTIVE` | hits=158; read=11; write=6; ops=76; idx=3 | ALTO |

### `app_kv` (AppKV)
- Model: `app/models/app_kv.py`
- Menções em migrations: 6

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `key` | `READ_ACTIVE` | hits=1311; read=61; write=73; ops=218; idx=29 | ALTO |
| `value` | `READ_ACTIVE` | hits=696; read=68; write=52; ops=12; idx=4 | ALTO |

### `auction_events` (AuctionEvent)
- Model: `app/models/auction_event.py`
- Menções em migrations: 0

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|

### `auction_lots` (AuctionLot)
- Model: `app/models/auction_lot.py`
- Menções em migrations: 0

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|

### `autopilot_findings` (AutopilotFinding)
- Model: `app/models/autopilot_finding.py`
- Menções em migrations: 14

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `evidence` | `READ_ACTIVE` | hits=49; read=7; write=7; ops=13; idx=2 | ALTO |
| `fingerprint` | `READ_ACTIVE` | hits=64; read=8; write=12; ops=32; idx=4 | ALTO |
| `first_seen_at` | `READ_ACTIVE` | hits=8; read=3; write=4; ops=2; idx=3 | ALTO |
| `hit_count` | `READ_ACTIVE` | hits=6; read=1; write=1; ops=6; idx=1 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `kind` | `READ_ACTIVE` | hits=165; read=19; write=24; ops=41; idx=4 | ALTO |
| `last_alert_at` | `READ_ACTIVE` | hits=4; read=1; write=1; ops=4; idx=1 | ALTO |
| `last_seen_at` | `READ_ACTIVE` | hits=41; read=15; write=9; ops=5; idx=6 | ALTO |
| `severity` | `READ_ACTIVE` | hits=31; read=3; write=3; ops=15; idx=1 | ALTO |
| `source` | `READ_ACTIVE` | hits=2244; read=141; write=121; ops=381; idx=14 | ALTO |
| `status` | `READ_ACTIVE` | hits=1069; read=97; write=67; ops=247; idx=13 | ALTO |
| `suggested_actions` | `READ_ACTIVE` | hits=12; read=1; write=1; ops=12; idx=1 | ALTO |
| `title` | `READ_ACTIVE` | hits=929; read=64; write=62; ops=19; idx=4 | ALTO |

### `car_listings` (CarListing)
- Model: `app/models/car_listing.py`
- Menções em migrations: 109

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `body_type` | `READ_ACTIVE` | hits=78; read=4; write=3; ops=0; idx=1 | ALTO |
| `city` | `READ_ACTIVE` | hits=219; read=32; write=16; ops=0; idx=3 | ALTO |
| `color` | `READ_ACTIVE` | hits=67; read=12; write=10; ops=0; idx=2 | ALTO |
| `cross_source_fingerprint` | `INDEX_OR_CONSTRAINT_ONLY` | hits=1; read=0; write=0; ops=0; idx=1 | ALTO |
| `currency` | `READ_ACTIVE` | hits=96; read=18; write=28; ops=1; idx=3 | ALTO |
| `doors` | `READ_ACTIVE` | hits=106; read=4; write=3; ops=0; idx=1 | ALTO |
| `external_id` | `READ_ACTIVE` | hits=493; read=54; write=56; ops=2; idx=4 | ALTO |
| `extractor_version` | `READ_ACTIVE` | hits=36; read=10; write=2; ops=0; idx=3 | ALTO |
| `extras` | `READ_ACTIVE` | hits=148; read=17; write=18; ops=1; idx=3 | ALTO |
| `fuel_type` | `READ_ACTIVE` | hits=68; read=8; write=3; ops=0; idx=2 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `is_sold` | `READ_ACTIVE` | hits=18; read=4; write=3; ops=0; idx=2 | ALTO |
| `listing_type` | `READ_ACTIVE` | hits=29; read=2; write=3; ops=0; idx=1 | ALTO |
| `location` | `READ_ACTIVE` | hits=396; read=45; write=37; ops=4; idx=3 | ALTO |
| `make` | `READ_ACTIVE` | hits=289; read=28; write=18; ops=2; idx=3 | ALTO |
| `mileage_km` | `READ_ACTIVE` | hits=158; read=22; write=12; ops=0; idx=2 | ALTO |
| `model` | `READ_ACTIVE` | hits=639; read=140; write=32; ops=52; idx=4 | ALTO |
| `price` | `READ_ACTIVE` | hits=1172; read=73; write=57; ops=11; idx=6 | ALTO |
| `raw_payload` | `READ_ACTIVE` | hits=41; read=10; write=2; ops=0; idx=3 | ALTO |
| `seller_type` | `READ_ACTIVE` | hits=105; read=8; write=8; ops=0; idx=1 | ALTO |
| `sold_at` | `READ_ACTIVE` | hits=13; read=1; write=1; ops=0; idx=1 | ALTO |
| `source` | `READ_ACTIVE` | hits=2244; read=141; write=121; ops=381; idx=14 | ALTO |
| `state` | `READ_ACTIVE` | hits=522; read=39; write=22; ops=29; idx=6 | ALTO |
| `thumbnail_url` | `READ_ACTIVE` | hits=188; read=31; write=23; ops=0; idx=2 | ALTO |
| `title` | `READ_ACTIVE` | hits=929; read=64; write=62; ops=19; idx=4 | ALTO |
| `transmission` | `READ_ACTIVE` | hits=108; read=11; write=9; ops=0; idx=2 | ALTO |
| `url` | `READ_ACTIVE` | hits=2444; read=94; write=98; ops=31; idx=7 | ALTO |
| `version` | `READ_ACTIVE` | hits=96; read=21; write=9; ops=0; idx=5 | ALTO |
| `year` | `READ_ACTIVE` | hits=678; read=46; write=26; ops=5; idx=3 | ALTO |

### `fb_agent_sessions` (FBAgentSession)
- Model: `app/models/fb_agent_session.py`
- Menções em migrations: 19

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `action_hint` | `READ_ACTIVE` | hits=29; read=5; write=3; ops=0; idx=1 | ALTO |
| `agent_id` | `READ_ACTIVE` | hits=8; read=2; write=0; ops=0; idx=1 | ALTO |
| `agent_version` | `READ_ACTIVE` | hits=8; read=2; write=0; ops=0; idx=1 | ALTO |
| `bootstrap_token` | `READ_ACTIVE` | hits=26; read=4; write=0; ops=0; idx=1 | ALTO |
| `bootstrap_token_expires_at` | `READ_ACTIVE` | hits=7; read=3; write=0; ops=0; idx=1 | ALTO |
| `bootstrap_token_used_at` | `READ_ACTIVE` | hits=4; read=1; write=0; ops=0; idx=1 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `last_check_at` | `READ_ACTIVE` | hits=9; read=5; write=0; ops=0; idx=2 | ALTO |
| `last_error_kind` | `READ_ACTIVE` | hits=14; read=6; write=1; ops=4; idx=2 | ALTO |
| `last_error_message` | `READ_ACTIVE` | hits=10; read=5; write=0; ops=0; idx=2 | ALTO |
| `last_ok_at` | `READ_ACTIVE` | hits=9; read=6; write=1; ops=2; idx=2 | ALTO |
| `last_seen_at` | `READ_ACTIVE` | hits=41; read=15; write=9; ops=5; idx=6 | ALTO |
| `pairing_code` | `READ_ACTIVE` | hits=113; read=8; write=0; ops=0; idx=2 | ALTO |
| `pairing_expires_at` | `READ_ACTIVE` | hits=14; read=6; write=0; ops=0; idx=2 | ALTO |
| `pairing_used_at` | `READ_ACTIVE` | hits=10; read=4; write=0; ops=0; idx=2 | ALTO |
| `status` | `READ_ACTIVE` | hits=1069; read=97; write=67; ops=247; idx=13 | ALTO |
| `user_id` | `READ_ACTIVE` | hits=419; read=47; write=53; ops=38; idx=7 | ALTO |

### `fb_sessions` (FBSession)
- Model: `app/models/fb_session.py`
- Menções em migrations: 15

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `last_check_at` | `READ_ACTIVE` | hits=9; read=5; write=0; ops=0; idx=2 | ALTO |
| `last_error_kind` | `READ_ACTIVE` | hits=14; read=6; write=1; ops=4; idx=2 | ALTO |
| `last_error_message` | `READ_ACTIVE` | hits=10; read=5; write=0; ops=0; idx=2 | ALTO |
| `last_ok_at` | `READ_ACTIVE` | hits=9; read=6; write=1; ops=2; idx=2 | ALTO |
| `pairing_code` | `READ_ACTIVE` | hits=113; read=8; write=0; ops=0; idx=2 | ALTO |
| `pairing_expires_at` | `READ_ACTIVE` | hits=14; read=6; write=0; ops=0; idx=2 | ALTO |
| `pairing_used_at` | `READ_ACTIVE` | hits=10; read=4; write=0; ops=0; idx=2 | ALTO |
| `profile_dir` | `READ_ACTIVE` | hits=29; read=2; write=2; ops=0; idx=1 | ALTO |
| `session_validated_at` | `READ_ACTIVE` | hits=6; read=3; write=0; ops=0; idx=1 | ALTO |
| `status` | `READ_ACTIVE` | hits=1069; read=97; write=67; ops=247; idx=13 | ALTO |
| `user_id` | `READ_ACTIVE` | hits=419; read=47; write=53; ops=38; idx=7 | ALTO |

### `fipe_prices` (FipePrice)
- Model: `app/models/fipe_price.py`
- Menções em migrations: 13

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `currency` | `READ_ACTIVE` | hits=96; read=18; write=28; ops=1; idx=3 | ALTO |
| `fipe_price` | `READ_ACTIVE` | hits=16; read=5; write=3; ops=0; idx=2 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `reference_month` | `READ_ACTIVE` | hits=5; read=1; write=0; ops=0; idx=1 | ALTO |
| `vehicle_key` | `READ_ACTIVE` | hits=5; read=1; write=0; ops=0; idx=1 | ALTO |

### `market_stats_cohorts` (MarketStatsCohort)
- Model: `app/models/market_stats.py`
- Menções em migrations: 16

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `computed_at` | `READ_ACTIVE` | hits=5; read=1; write=0; ops=0; idx=1 | ALTO |
| `make` | `READ_ACTIVE` | hits=289; read=28; write=18; ops=2; idx=3 | ALTO |
| `median_price` | `READ_ACTIVE` | hits=15; read=3; write=4; ops=0; idx=1 | ALTO |
| `model` | `READ_ACTIVE` | hits=639; read=140; write=32; ops=52; idx=4 | ALTO |
| `p25_price` | `READ_ACTIVE` | hits=14; read=3; write=3; ops=0; idx=1 | ALTO |
| `p75_price` | `READ_ACTIVE` | hits=14; read=3; write=3; ops=0; idx=1 | ALTO |
| `sample_size` | `READ_ACTIVE` | hits=16; read=3; write=4; ops=0; idx=1 | ALTO |
| `year` | `READ_ACTIVE` | hits=678; read=46; write=26; ops=5; idx=3 | ALTO |

### `notifications` (Notification)
- Model: `app/models/notification.py`
- Menções em migrations: 88

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `attempts` | `READ_ACTIVE` | hits=45; read=12; write=11; ops=1; idx=2 | ALTO |
| `car_listing_id` | `READ_ACTIVE` | hits=97; read=19; write=19; ops=2; idx=3 | ALTO |
| `error_message` | `READ_ACTIVE` | hits=78; read=12; write=7; ops=33; idx=4 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `max_attempts` | `READ_ACTIVE` | hits=33; read=9; write=9; ops=0; idx=2 | ALTO |
| `next_attempt_at` | `READ_ACTIVE` | hits=15; read=5; write=4; ops=0; idx=1 | ALTO |
| `processing_owner` | `READ_ACTIVE` | hits=10; read=2; write=1; ops=0; idx=1 | ALTO |
| `processing_started_at` | `READ_ACTIVE` | hits=13; read=3; write=1; ops=0; idx=1 | ALTO |
| `reason` | `READ_ACTIVE` | hits=491; read=46; write=39; ops=33; idx=2 | ALTO |
| `score_breakdown` | `READ_ACTIVE` | hits=28; read=6; write=5; ops=0; idx=1 | ALTO |
| `score_v2` | `READ_ACTIVE` | hits=32; read=7; write=5; ops=0; idx=1 | ALTO |
| `sent_at` | `READ_ACTIVE` | hits=35; read=10; write=5; ops=3; idx=1 | ALTO |
| `status` | `READ_ACTIVE` | hits=1069; read=97; write=67; ops=247; idx=13 | ALTO |
| `user_id` | `READ_ACTIVE` | hits=419; read=47; write=53; ops=38; idx=7 | ALTO |
| `wishlist_id` | `READ_ACTIVE` | hits=325; read=29; write=36; ops=3; idx=6 | ALTO |

### `plans` (Plan)
- Model: `app/models/plan.py`
- Menções em migrations: 25

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `code` | `READ_ACTIVE` | hits=567; read=52; write=38; ops=57; idx=3 | ALTO |
| `daily_alert_limit` | `READ_ACTIVE` | hits=49; read=12; write=11; ops=7; idx=2 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `is_active` | `READ_ACTIVE` | hits=174; read=33; write=45; ops=19; idx=4 | ALTO |
| `max_wishlists` | `READ_ACTIVE` | hits=47; read=10; write=9; ops=6; idx=1 | ALTO |
| `name` | `READ_ACTIVE` | hits=864; read=81; write=104; ops=87; idx=29 | ALTO |

### `scrape_jobs` (ScrapeJob)
- Model: `app/models/scrape_job.py`
- Menções em migrations: 39

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `attempt` | `READ_ACTIVE` | hits=122; read=18; write=10; ops=10; idx=2 | ALTO |
| `duration_ms` | `READ_ACTIVE` | hits=127; read=8; write=17; ops=14; idx=2 | ALTO |
| `error` | `READ_ACTIVE` | hits=740; read=69; write=31; ops=237; idx=11 | ALTO |
| `finished_at` | `READ_ACTIVE` | hits=16; read=4; write=2; ops=12; idx=2 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `lock_owner` | `READ_ACTIVE` | hits=13; read=2; write=4; ops=0; idx=1 | ALTO |
| `locked_at` | `READ_ACTIVE` | hits=8; read=2; write=2; ops=0; idx=1 | ALTO |
| `max_attempts` | `READ_ACTIVE` | hits=33; read=9; write=9; ops=0; idx=2 | ALTO |
| `priority` | `READ_ACTIVE` | hits=40; read=8; write=7; ops=0; idx=1 | ALTO |
| `queue` | `READ_ACTIVE` | hits=575; read=25; write=19; ops=80; idx=3 | ALTO |
| `result_payload` | `READ_ACTIVE` | hits=2; read=1; write=1; ops=0; idx=1 | ALTO |
| `result_status` | `READ_ACTIVE` | hits=11; read=2; write=3; ops=0; idx=1 | ALTO |
| `run_at` | `READ_ACTIVE` | hits=59; read=9; write=10; ops=13; idx=2 | ALTO |
| `source` | `READ_ACTIVE` | hits=2244; read=141; write=121; ops=381; idx=14 | ALTO |
| `started_at` | `READ_ACTIVE` | hits=55; read=11; write=7; ops=18; idx=3 | ALTO |
| `status` | `READ_ACTIVE` | hits=1069; read=97; write=67; ops=247; idx=13 | ALTO |

### `source_configs` (SourceConfig)
- Model: `app/models/source_config.py`
- Menções em migrations: 33

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `browser_fallback_enabled` | `READ_ACTIVE` | hits=68; read=10; write=18; ops=8; idx=2 | ALTO |
| `cooldown_minutes` | `READ_ACTIVE` | hits=66; read=11; write=11; ops=9; idx=1 | ALTO |
| `extra` | `READ_ACTIVE` | hits=700; read=57; write=45; ops=26; idx=4 | ALTO |
| `force_browser` | `READ_ACTIVE` | hits=87; read=14; write=17; ops=10; idx=2 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `is_enabled` | `READ_ACTIVE` | hits=74; read=19; write=13; ops=16; idx=1 | ALTO |
| `proxy_server` | `READ_ACTIVE` | hits=133; read=16; write=22; ops=8; idx=2 | ALTO |
| `rate_limit_seconds` | `READ_ACTIVE` | hits=60; read=12; write=12; ops=17; idx=1 | ALTO |
| `sched_minutes` | `READ_ACTIVE` | hits=83; read=10; write=16; ops=22; idx=1 | ALTO |
| `source` | `READ_ACTIVE` | hits=2244; read=141; write=121; ops=381; idx=14 | ALTO |

### `source_runs` (SourceRun)
- Model: `app/models/source_run.py`
- Menções em migrations: 42

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `browser_fallback_enabled` | `READ_ACTIVE` | hits=68; read=10; write=18; ops=8; idx=2 | ALTO |
| `duration_ms` | `READ_ACTIVE` | hits=127; read=8; write=17; ops=14; idx=2 | ALTO |
| `error` | `READ_ACTIVE` | hits=740; read=69; write=31; ops=237; idx=11 | ALTO |
| `force_browser` | `READ_ACTIVE` | hits=87; read=14; write=17; ops=10; idx=2 | ALTO |
| `groups` | `READ_ACTIVE` | hits=59; read=4; write=4; ops=0; idx=1 | ALTO |
| `http_status` | `READ_ACTIVE` | hits=81; read=10; write=12; ops=27; idx=1 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `items_found` | `READ_ACTIVE` | hits=21; read=5; write=5; ops=6; idx=1 | ALTO |
| `items_ingested` | `READ_ACTIVE` | hits=6; read=2; write=3; ops=0; idx=1 | ALTO |
| `items_matched` | `READ_ACTIVE` | hits=8; read=2; write=3; ops=3; idx=1 | ALTO |
| `kind` | `READ_ACTIVE` | hits=165; read=19; write=24; ops=41; idx=4 | ALTO |
| `notifications_queued` | `READ_ACTIVE` | hits=5; read=1; write=2; ops=0; idx=1 | ALTO |
| `payload` | `READ_ACTIVE` | hits=496; read=36; write=28; ops=57; idx=7 | ALTO |
| `proxy_server` | `READ_ACTIVE` | hits=133; read=16; write=22; ops=8; idx=2 | ALTO |
| `query` | `READ_ACTIVE` | hits=927; read=108; write=73; ops=75; idx=4 | ALTO |
| `source` | `READ_ACTIVE` | hits=2244; read=141; write=121; ops=381; idx=14 | ALTO |
| `status` | `READ_ACTIVE` | hits=1069; read=97; write=67; ops=247; idx=13 | ALTO |
| `url` | `READ_ACTIVE` | hits=2444; read=94; write=98; ops=31; idx=7 | ALTO |
| `wishlists` | `READ_ACTIVE` | hits=581; read=46; write=26; ops=28; idx=11 | ALTO |

### `source_states` (SourceState)
- Model: `app/models/source_state.py`
- Menções em migrations: 29

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `consecutive_blocks` | `READ_ACTIVE` | hits=13; read=4; write=2; ops=2; idx=1 | ALTO |
| `consecutive_failures` | `READ_ACTIVE` | hits=13; read=4; write=2; ops=2; idx=1 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `last_admin_alert_at` | `INDEX_OR_CONSTRAINT_ONLY` | hits=1; read=0; write=0; ops=0; idx=1 | ALTO |
| `last_admin_alert_error_hash` | `INDEX_OR_CONSTRAINT_ONLY` | hits=1; read=0; write=0; ops=0; idx=1 | ALTO |
| `last_admin_alert_status` | `INDEX_OR_CONSTRAINT_ONLY` | hits=1; read=0; write=0; ops=0; idx=1 | ALTO |
| `last_effective_run_at` | `READ_ACTIVE` | hits=15; read=5; write=3; ops=0; idx=1 | ALTO |
| `last_error` | `READ_ACTIVE` | hits=58; read=9; write=5; ops=19; idx=3 | ALTO |
| `last_payload` | `READ_ACTIVE` | hits=7; read=1; write=0; ops=0; idx=1 | ALTO |
| `last_run_at` | `READ_ACTIVE` | hits=25; read=5; write=4; ops=10; idx=1 | ALTO |
| `last_status` | `READ_ACTIVE` | hits=18; read=4; write=5; ops=3; idx=1 | ALTO |
| `next_allowed_at` | `READ_ACTIVE` | hits=50; read=5; write=5; ops=11; idx=1 | ALTO |
| `source` | `READ_ACTIVE` | hits=2244; read=141; write=121; ops=381; idx=14 | ALTO |

### `source_url_cursors` (SourceUrlCursor)
- Model: `app/models/source_url_cursor.py`
- Menções em migrations: 16

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `last_checked_at` | `READ_ACTIVE` | hits=3; read=1; write=0; ops=0; idx=1 | ALTO |
| `last_external_id` | `READ_ACTIVE` | hits=12; read=2; write=1; ops=0; idx=1 | ALTO |
| `last_seen_at` | `READ_ACTIVE` | hits=41; read=15; write=9; ops=5; idx=6 | ALTO |
| `runs` | `READ_ACTIVE` | hits=77; read=13; write=7; ops=15; idx=6 | ALTO |
| `source` | `READ_ACTIVE` | hits=2244; read=141; write=121; ops=381; idx=14 | ALTO |
| `url` | `READ_ACTIVE` | hits=2444; read=94; write=98; ops=31; idx=7 | ALTO |

### `subscriptions` (Subscription)
- Model: `app/models/subscription.py`
- Menções em migrations: 27

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `account_id` | `READ_ACTIVE` | hits=80; read=11; write=13; ops=14; idx=4 | ALTO |
| `cancel_at_period_end` | `INDEX_OR_CONSTRAINT_ONLY` | hits=1; read=0; write=0; ops=0; idx=1 | ALTO |
| `current_period_end` | `READ_ACTIVE` | hits=23; read=5; write=5; ops=2; idx=1 | ALTO |
| `current_period_start` | `READ_ACTIVE` | hits=6; read=2; write=2; ops=0; idx=1 | ALTO |
| `daily_alert_limit_override` | `READ_ACTIVE` | hits=6; read=3; write=1; ops=1; idx=1 | ALTO |
| `ends_at` | `READ_ACTIVE` | hits=16; read=4; write=3; ops=4; idx=1 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `metadata_json` | `READ_ACTIVE` | hits=2; read=1; write=1; ops=0; idx=1 | ALTO |
| `plan_id` | `READ_ACTIVE` | hits=30; read=10; write=10; ops=3; idx=1 | ALTO |
| `source` | `READ_ACTIVE` | hits=2244; read=141; write=121; ops=381; idx=14 | ALTO |
| `starts_at` | `READ_ACTIVE` | hits=18; read=6; write=6; ops=6; idx=1 | ALTO |
| `status` | `READ_ACTIVE` | hits=1069; read=97; write=67; ops=247; idx=13 | ALTO |

### `system_logs` (SystemLog)
- Model: `app/models/system_log.py`
- Menções em migrations: 62

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `component` | `READ_ACTIVE` | hits=100; read=20; write=18; ops=27; idx=1 | ALTO |
| `event_type` | `READ_ACTIVE` | hits=67; read=6; write=8; ops=16; idx=2 | ALTO |
| `fingerprint` | `READ_ACTIVE` | hits=64; read=8; write=12; ops=32; idx=4 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `level` | `READ_ACTIVE` | hits=66; read=11; write=12; ops=21; idx=2 | ALTO |
| `message` | `READ_ACTIVE` | hits=651; read=63; write=39; ops=169; idx=6 | ALTO |
| `payload` | `READ_ACTIVE` | hits=496; read=36; write=28; ops=57; idx=7 | ALTO |
| `run_id` | `READ_ACTIVE` | hits=38; read=3; write=5; ops=6; idx=3 | ALTO |
| `source` | `READ_ACTIVE` | hits=2244; read=141; write=121; ops=381; idx=14 | ALTO |
| `tags` | `READ_ACTIVE` | hits=59; read=7; write=10; ops=8; idx=2 | ALTO |

### `telemetry_events` (TelemetryEvent)
- Model: `app/models/telemetry_event.py`
- Menções em migrations: 43

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `account_id` | `READ_ACTIVE` | hits=80; read=11; write=13; ops=14; idx=4 | ALTO |
| `event_type` | `READ_ACTIVE` | hits=67; read=6; write=8; ops=16; idx=2 | ALTO |
| `evidence` | `READ_ACTIVE` | hits=49; read=7; write=7; ops=13; idx=2 | ALTO |
| `fingerprint` | `READ_ACTIVE` | hits=64; read=8; write=12; ops=32; idx=4 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `level` | `READ_ACTIVE` | hits=66; read=11; write=12; ops=21; idx=2 | ALTO |
| `message` | `READ_ACTIVE` | hits=651; read=63; write=39; ops=169; idx=6 | ALTO |
| `run_id` | `READ_ACTIVE` | hits=38; read=3; write=5; ops=6; idx=3 | ALTO |
| `source` | `READ_ACTIVE` | hits=2244; read=141; write=121; ops=381; idx=14 | ALTO |
| `tags` | `READ_ACTIVE` | hits=59; read=7; write=10; ops=8; idx=2 | ALTO |
| `user_id` | `READ_ACTIVE` | hits=419; read=47; write=53; ops=38; idx=7 | ALTO |
| `wishlist_id` | `READ_ACTIVE` | hits=325; read=29; write=36; ops=3; idx=6 | ALTO |

### `users` (User)
- Model: `app/models/user.py`
- Menções em migrations: 58

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `account_id` | `READ_ACTIVE` | hits=80; read=11; write=13; ops=14; idx=4 | ALTO |
| `daily_limit_override` | `READ_ACTIVE` | hits=3; read=1; write=1; ops=2; idx=1 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `is_active` | `READ_ACTIVE` | hits=174; read=33; write=45; ops=19; idx=4 | ALTO |
| `last_daily_limit_notice_at` | `READ_ACTIVE` | hits=4; read=3; write=0; ops=0; idx=1 | ALTO |
| `plan` | `READ_ACTIVE` | hits=396; read=30; write=10; ops=55; idx=4 | ALTO |
| `telegram_chat_id` | `READ_ACTIVE` | hits=84; read=25; write=41; ops=10; idx=1 | ALTO |
| `username` | `READ_ACTIVE` | hits=145; read=29; write=49; ops=22; idx=2 | ALTO |

### `wishlist_filters` (WishlistFilter)
- Model: `app/models/wishlist_filter.py`
- Menções em migrations: 28

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `field` | `READ_ACTIVE` | hits=512; read=39; write=29; ops=14; idx=4 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `operator` | `READ_ACTIVE` | hits=209; read=21; write=21; ops=1; idx=1 | ALTO |
| `value` | `READ_ACTIVE` | hits=696; read=68; write=52; ops=12; idx=4 | ALTO |
| `wishlist_id` | `READ_ACTIVE` | hits=325; read=29; write=36; ops=3; idx=6 | ALTO |

### `wishlist_listing_activity` (WishlistListingActivity)
- Model: `app/models/wishlist_listing_activity.py`
- Menções em migrations: 15

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `car_listing_id` | `READ_ACTIVE` | hits=97; read=19; write=19; ops=2; idx=3 | ALTO |
| `first_seen_at` | `READ_ACTIVE` | hits=8; read=3; write=4; ops=2; idx=3 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `inactive_at` | `READ_ACTIVE` | hits=5; read=2; write=1; ops=0; idx=1 | ALTO |
| `inactive_reason` | `READ_ACTIVE` | hits=4; read=1; write=1; ops=0; idx=1 | ALTO |
| `last_seen_at` | `READ_ACTIVE` | hits=41; read=15; write=9; ops=5; idx=6 | ALTO |
| `last_valid_run_id` | `READ_ACTIVE` | hits=4; read=1; write=1; ops=0; idx=1 | ALTO |
| `listing_identity_key` | `READ_ACTIVE` | hits=17; read=2; write=3; ops=0; idx=1 | ALTO |
| `listing_url` | `READ_ACTIVE` | hits=38; read=6; write=6; ops=0; idx=1 | ALTO |
| `missing_runs_count` | `READ_ACTIVE` | hits=17; read=2; write=2; ops=0; idx=1 | ALTO |
| `reactivated_at` | `READ_ACTIVE` | hits=4; read=2; write=1; ops=0; idx=1 | ALTO |
| `source_listing_id` | `READ_ACTIVE` | hits=22; read=3; write=3; ops=0; idx=1 | ALTO |
| `source_name` | `READ_ACTIVE` | hits=94; read=15; write=20; ops=7; idx=1 | ALTO |
| `status` | `READ_ACTIVE` | hits=1069; read=97; write=67; ops=247; idx=13 | ALTO |
| `wishlist_id` | `READ_ACTIVE` | hits=325; read=29; write=36; ops=3; idx=6 | ALTO |

### `wishlist_tokens` (WishlistToken)
- Model: `app/models/wishlist_token.py`
- Menções em migrations: 21

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `created_at` | `READ_ACTIVE` | hits=209; read=38; write=19; ops=78; idx=3 | ALTO |
| `token` | `READ_ACTIVE` | hits=458; read=33; write=19; ops=40; idx=4 | ALTO |
| `wishlist_id` | `READ_ACTIVE` | hits=325; read=29; write=36; ops=3; idx=6 | ALTO |

### `wishlist_tracked_listings` (WishlistTrackedListing)
- Model: `app/models/wishlist_tracked_listing.py`
- Menções em migrations: 36

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `car_listing_id` | `READ_ACTIVE` | hits=97; read=19; write=19; ops=2; idx=3 | ALTO |
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `initial_price` | `READ_ACTIVE` | hits=12; read=3; write=2; ops=0; idx=1 | ALTO |
| `last_observed_price` | `READ_ACTIVE` | hits=15; read=4; write=3; ops=0; idx=1 | ALTO |
| `last_price_change_amount` | `READ_ACTIVE` | hits=9; read=4; write=1; ops=0; idx=1 | ALTO |
| `last_price_change_at` | `READ_ACTIVE` | hits=2; read=1; write=0; ops=0; idx=1 | ALTO |
| `last_price_change_direction` | `READ_ACTIVE` | hits=3; read=2; write=1; ops=0; idx=1 | ALTO |
| `last_price_change_pct` | `READ_ACTIVE` | hits=6; read=3; write=1; ops=0; idx=1 | ALTO |
| `last_price_drop_alert_at` | `READ_ACTIVE` | hits=6; read=2; write=0; ops=0; idx=1 | ALTO |
| `last_price_drop_alert_price` | `READ_ACTIVE` | hits=5; read=1; write=0; ops=0; idx=1 | ALTO |
| `last_seen_at` | `READ_ACTIVE` | hits=41; read=15; write=9; ops=5; idx=6 | ALTO |
| `listing_status` | `READ_ACTIVE` | hits=12; read=1; write=1; ops=0; idx=1 | ALTO |
| `price_drop_alert_enabled` | `READ_ACTIVE` | hits=19; read=4; write=2; ops=0; idx=1 | ALTO |
| `slot` | `READ_ACTIVE` | hits=182; read=12; write=12; ops=0; idx=1 | ALTO |
| `wishlist_id` | `READ_ACTIVE` | hits=325; read=29; write=36; ops=3; idx=6 | ALTO |

### `wishlists` (Wishlist)
- Model: `app/models/wishlist.py`
- Menções em migrations: 58

| Coluna | Classificação | Evidência (heurística) | Risco de remoção |
|---|---|---:|---|
| `id` | `READ_ACTIVE` | hits=5565; read=154; write=161; ops=530; idx=28 | ALTO |
| `is_active` | `READ_ACTIVE` | hits=174; read=33; write=45; ops=19; idx=4 | ALTO |
| `query` | `READ_ACTIVE` | hits=927; read=108; write=73; ops=75; idx=4 | ALTO |
| `user_id` | `READ_ACTIVE` | hits=419; read=47; write=53; ops=38; idx=7 | ALTO |

