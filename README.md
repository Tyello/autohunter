# AutoHunter

AutoHunter é uma plataforma **Telegram-first** de monitoramento recorrente de anúncios de carros usados.

> Produto principal hoje: bot no Telegram + runtime contínuo (scheduler, filas, workers, matching e envio de notificações).
>
> A API FastAPI existe como superfície **auxiliar/operacional/integrativa** (healthchecks, listagem simples e fluxo Facebook Agent), não como jornada principal do usuário final.

## O que o produto é hoje

- Usuário final cria e gerencia wishlists pelo Telegram.
- O sistema roda continuamente para monitorar fontes e encontrar anúncios novos.
- Listings são normalizados, deduplicados e avaliados por matching.
- Notificações são enfileiradas e enviadas no Telegram.
- Há trilha operacional: backoff, monitoramento admin, health e digest.

Fluxo resumido (runtime):

`wishlist -> scheduler tick -> scrape_jobs -> workers http/browser -> scrape+normalização+ingestão -> dedupe -> matching -> notifications -> sender Telegram`

## Superfícies do sistema

- **Principal (produto):** Telegram (`app/bot/`).
- **Núcleo operacional:** scheduler + workers + serviços (`app/scheduler/`, `app/services/`).
- **Auxiliar:** API FastAPI (`app/main.py`, `app/web/`).

## Estado das sources (importante)

As fontes implementadas ficam em `app/sources/builtins.py`, mas o estado efetivo de operação (enabled, cadência, backoff, browser fallback etc.) é **DB-driven** por `source_configs` e `source_states`.

Ou seja: “fonte ativa” depende do banco/runtime atual, não só de flag em documento.

## Leitura recomendada

- [`AGENTS.md`](AGENTS.md) — mapa mental curto para pessoas técnicas e IAs.
- [`docs/PROJECT_GUIDELINE.md`](docs/PROJECT_GUIDELINE.md) — documentação viva do runtime atual.
- [`docs/LEGACY_INVENTORY.md`](docs/LEGACY_INVENTORY.md) — inventário de legado/compatibilidade e risco de remoção.
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md) — runbook operacional curto (saúde, diagnóstico, recovery).
