# AGENTS.md — AutoHunter

Marca pública: Garagem Alvo.
Nome interno/runtime/repo: AutoHunter.

## O que este projeto é
AutoHunter é o runtime interno de um produto público chamado Garagem Alvo.

Não é web-first e não é apenas scraping manual: o runtime central é recorrente.

## Caminho oficial do produto
Fluxo principal observado no código:

`wishlist -> scheduler tick -> enqueue scrape_jobs -> workers (http/browser) -> scrape+normalização+ingestão -> dedupe -> matching -> queue de notifications -> sender Telegram`

## Papel da API
A API/FastAPI é superfície **auxiliar** (health/admin/integrativa, incluindo Facebook Agent).
A jornada principal de usuário final ocorre no Telegram.

## Fonte de verdade
1. **Código atual** > documentação histórica.
2. Configuração operacional de fontes é majoritariamente **DB-driven** (`source_configs`, `source_states`), com seed/default vindo dos plugins.
3. Sempre diferencie explicitamente: fato confirmado no runtime vs hipótese.

## Como trabalhar sem quebrar o repo
- Faça mudanças incrementais e reversíveis.
- Preserve contratos de scheduler, filas, matching e notificações.
- Não redesenhe arquitetura sem necessidade explícita.
- Não remova “legado” sem evidência de uso (import/call/dados/operação).
- Separe claramente: bug real, risco operacional, melhoria técnica, melhoria de produto.

## Áreas que exigem cautela
- Coexistência de caminhos v1/v2/dual em scraping/adaptação.
- Comandos/fluxos de compatibilidade no bot (UX antiga + UX nova).
- Integrações operacionais auxiliares (ex.: Facebook Agent, admin deploy, autopilot).

## Ordem de leitura recomendada
1. `README.md`
2. `docs/PROJECT_GUIDELINE.md`
3. `docs/OPERATIONS_RUNBOOK.md`
4. `docs/LEGACY_INVENTORY.md`
5. Código: `app/bot/`, `app/scheduler/`, `app/services/source_execution_service.py`, `app/sources/`, `app/models/`
