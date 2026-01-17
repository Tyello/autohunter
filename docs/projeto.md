# Documentação geral do projeto (AutoHunter)

## Objetivo

O AutoHunter monitora anúncios de carros em múltiplas fontes e envia alertas para usuários no Telegram.

Pilares:
- **MVP pragmático:** pouca magia, muita previsibilidade.
- **Deduplicação forte:** `source + external_id`.
- **Escala por plugins:** novas fontes entram sem explodir o scheduler.

## Visão de alto nível

Entradas:
- Comandos do usuário no Telegram (busca/wishlist)
- Scheduler coletando anúncios continuamente

Saídas:
- Notificações no Telegram
- Persistência no Postgres (Supabase ou Postgres local)

## Componentes

### 1) Telegram Bot

**Caminho:** `app/bot/*`

Responsável por:
- receber comandos (`/buscar`, `/wishlist`, `/alertas`, ...)
- criar/alterar registros no banco (usuário, wishlists, limites)
- formatar e enviar respostas

Entrypoint:
- `python -m app.bot.run`

### 2) Scheduler

**Caminho:** `app/scheduler/*`

Responsável por:
- rodar jobs por fonte
- coletar anúncios -> ingerir -> fazer matching -> gerar notifications
- enviar notificações pendentes (sender job)

Entrypoints:
- standalone: `python -m app.scheduler.cli`
- embutido na API (opcional): `ENABLE_SCHEDULER_IN_API=true`

### 3) API (FastAPI)

**Caminho:** `app/main.py`

Endpoints simples (MVP):
- `/health`
- `/db-check`
- `/listings`

Entrypoint:
- `uvicorn app.main:app --reload`

### 4) Scrapers

**Caminho:** `app/scrapers/*`

Regras:
- retornar `list[dict]` compatível com `ingest_listings`
- lançar `FetchBlocked` quando houver bloqueio

### 5) Serviços de domínio

**Caminho:** `app/services/*`

Onde vivem as regras do negócio:
- ingest/dedupe
- matching wishlist
- limites de alertas
- logs

## Banco de dados (tabelas principais)

> As migrations estão em `migrations/`.

- `users`: usuário do Telegram
- `wishlists`: queries ativas por usuário
- `wishlist_filters`: filtros extras (ex.: restringir por fonte)
- `car_listings`: anúncios coletados (deduplicados)
- `notifications`: fila de notificações para o usuário
- `system_logs`: trilha de auditoria (scrape bloqueado, erros, etc.)

## Fluxo de dados (fim-a-fim)

1) Usuário cria uma wishlist
2) Scheduler roda por fonte
3) Para cada wishlist ativa:
   - constrói URL de busca
   - faz scrape
   - ingere em `car_listings` (dedupe)
   - roda matching e cria `notifications`
4) Sender job lê `notifications` pendentes e envia no Telegram

## Framework de fontes pluginável

**Caminho:** `app/sources/*`

- `types.py`: `SourcePlugin` (contrato)
- `registry.py`: registro e listagem
- `builtins.py`: plugins nativos

O scheduler não tem mais `if/elif` por fonte: ele percorre o registry e agenda automaticamente todos os plugins com `sched_minutes_setting`.

### Adicionar uma nova fonte

Checklist:
1) implementar scraper (`app/scrapers/`)
2) implementar builder de URL (`app/services/search_urls_service.py`)
3) registrar plugin (`app/sources/builtins.py`)
4) adicionar settings + env vars (`app/core/settings.py` + `.env`)

## Operação e observabilidade

- Bloqueios e erros de scrape viram registros em `system_logs`
- Configure cooldowns por fonte para reduzir ban

## Deploy (visão)

O projeto roda bem em 2 processos:
- `bot` (polling)
- `scheduler` (APScheduler)

E opcionalmente um 3º:
- `api`

No Supabase, você só precisa apontar `DATABASE_URL`.
