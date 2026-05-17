# AGENTS.md — AutoHunter

Marca pública: Garagem Alvo.  
Nome interno/runtime/repo: AutoHunter.

## O que este projeto é

AutoHunter é o runtime interno de um produto público chamado Garagem Alvo.

Não é web-first e não é apenas scraping manual: o runtime central é recorrente, Telegram-first e orientado a operação contínua.

## Caminho oficial do produto

Fluxo principal para anúncios tradicionais:

`wishlist -> scheduler tick -> enqueue scrape_jobs -> workers (http/browser) -> scrape+normalização+ingestão -> dedupe -> matching -> queue de notifications -> sender Telegram`

Fluxo atual de leilões:

`wishlist include_auctions -> auction_lots -> source_configs/user_eligible/categorias -> matching -> gates de notificação -> dry-run/samples/notify controlado`

## Papel da API

A API/FastAPI é superfície **auxiliar** (health/admin/integrativa). A jornada principal de usuário final ocorre no Telegram.

## Fonte de verdade

1. **Código atual** > documentação histórica.
2. Configuração operacional de sources é DB-driven (`source_configs`, `source_states`), com seed/default vindo dos plugins/registries.
3. Configuração runtime de notificações de leilão fica em `AppKV` (`auction_notification_settings`) com fallback em settings/env.
4. `.env` deve ser tratado como fallback/kill switch/bootstrapping, não como única superfície operacional de produto.
5. Sempre diferencie: fato confirmado no runtime vs hipótese.

## Estado atual de leilões

- Leilões não são mais apenas POC admin-only.
- Usuário pode optar por leilões por busca (`include_auctions`).
- Admin controla sources, elegibilidade e categorias permitidas.
- No piloto, apenas `car` deve chegar ao usuário; motos/caminhões/pesados/imóveis/outros ficam bloqueados por padrão.
- Scheduler de leilões pode rodar em dry-run automático; envio real automático continua bloqueado via comando admin nesta fase (`dry_run=false` não é permitido pelo comando de settings).
- Qualquer alerta user-facing de leilão deve conter disclosure: `Lance não é preço final.` e orientação sobre edital, taxas/comissão, documentação e vistoria.

## Como trabalhar sem quebrar o repo

- Faça mudanças incrementais e reversíveis.
- Preserve contratos de scheduler, filas, matching e notificações.
- Não redesenhe arquitetura sem necessidade explícita.
- Não remova legado sem evidência de uso (import/call/dados/operação).
- Separe claramente: bug real, risco operacional, melhoria técnica, melhoria de produto.
- Para leilões, preserve sempre os gates: opt-in da wishlist, source user_eligible, categoria permitida, lance, score mínimo, lote recente, dedupe e limite diário.

## Áreas que exigem cautela

- Coexistência de caminhos v1/v2/dual em scraping/adaptação.
- Comandos/fluxos de compatibilidade no bot (UX antiga + UX nova).
- Integrações operacionais auxiliares (admin deploy, autopilot, Facebook Agent).
- `source_configs.extra` e `AppKV`: são flexíveis, mas exigem validação rigorosa e testes.
- Scheduler de leilões: nunca liberar envio real automático sem decisão explícita e nova trava/revisão.

## Ordem de leitura recomendada

1. `README.md`
2. `docs/PROJECT_GUIDELINE.md`
3. `docs/AUCTION_RUNTIME.md`
4. `docs/OPERATIONS_RUNBOOK.md`
5. `docs/LEGACY_INVENTORY.md`
6. Código: `app/bot/`, `app/scheduler/`, `app/services/`, `app/sources/`, `app/models/`
