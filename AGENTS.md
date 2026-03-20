# AGENTS.md — AutoHunter

## What this project is
AutoHunter é uma plataforma **Telegram-first** para monitoramento contínuo de anúncios de carros usados em múltiplas fontes. Não é apenas scraping pontual: o runtime principal é recorrente (scheduler + filas + workers + matching + notificação).

## Primary purpose
Servir usuários que querem ser avisados quando surgirem anúncios que batem com suas wishlists, reduzindo busca manual e latência entre publicação e descoberta.

## Current operational model
Fluxo principal observado no código:
**wishlist -> scheduler tick -> enqueue scrape jobs -> queue workers (http/browser) -> scrape+normalize+ingest -> dedupe -> matching -> notifications queue -> sender (Telegram)**.
Há também trilha de operação/admin (health, backoff, staleness, alertas, comandos administrativos e digest).

## Core concepts
- Wishlist
- Source
- Listing / car listing
- Matching
- Notification
- Digest
- Source config
- Admin/monitoring
- Queue/job/worker
- Backoff / health

## Source of truth
- O **código atual** é fonte de verdade superior a docs históricas.
- Configuração operacional de source é majoritariamente **DB-driven** (`source_configs`, `source_states`) com fallback para defaults de plugin.
- Diferencie explicitamente comportamento confirmado em runtime vs contexto histórico em docs.

## How to work safely in this repo
- Não redesenhe a arquitetura inteira.
- Trabalhe incrementalmente, preservando contratos existentes.
- Separe claramente: bug real, risco operacional, melhoria técnica e melhoria de produto.
- Valide usos reais antes de remover qualquer trecho suspeito de legado.
- Não assuma que arquivo antigo está morto sem evidência de execução/import/uso.

## What seems legacy or needs caution
- Há coexistência de caminhos v1/v2/dual em scraping/adaptação.
- Existem modos manuais, admin e integrações auxiliares (ex.: Facebook Agent) que não devem ser removidos sem validação.
- Docs antigas são contexto útil, mas não devem sobrepor comportamento efetivo observado no código.

## Recommended first reading path
1. `README.md`
2. `docs/PROJECT_GUIDELINE.md`
3. `app/bot/` (superfície principal Telegram)
4. `app/scheduler/` (ticks, filas, workers, sender, monitor)
5. `app/services/source_execution_service.py` + `app/services/*` (ingest/match/notificação/backoff)
6. `app/sources/` e `app/scrapers/` (plugins, estratégias por fonte)
7. `app/models/` (entidades persistidas)
