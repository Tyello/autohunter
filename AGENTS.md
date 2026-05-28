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

Fluxo principal de usuário:

`/start ou /menu -> criar busca -> revisar filtros/leilões -> monitoramento -> alerta -> abrir anúncio ou rastrear -> plano/upgrade conforme limite`

Fluxos detalhados: `docs/USER_FLOWS.md`.

## Papel da API

A API/FastAPI é superfície **auxiliar** (health/admin/integrativa). A jornada principal de usuário final ocorre no Telegram.

## Fonte de verdade

1. **Código atual** > documentação histórica.
2. Configuração operacional de sources é DB-driven (`source_configs`, `source_states`), com seed/default vindo dos plugins/registries.
3. Configuração runtime de notificações de leilão fica em `AppKV` (`auction_notification_settings`) com fallback em settings/env.
4. `.env` deve ser tratado como fallback/kill switch/bootstrapping, não como única superfície operacional de produto.
5. Sempre diferencie: fato confirmado no runtime vs hipótese.

## Estado atual de produto

Já existem:

- bot Telegram com `/start`, `/menu`, comandos públicos e admin;
- criação guiada de busca com filtros implícitos e filtros guiados;
- copy pós-criação específica para busca monitorada, varredura em andamento, envio imediato quando houver dado e falha de agendamento;
- listagem/pausa/reativação/remoção de buscas;
- busca manual/pontual (`/buscar` e menu);
- tracking de anúncios por wishlist;
- plano Free/Premium, `/plan`, `/upgrade` e ativação Premium manual/admin;
- alertas com score, contexto mínimo, recência, contexto conservador de preço e contexto conservador de raridade/frequência quando há amostra mínima;
- digest semanal v2 comunicando monitoramento mesmo sem anúncios ativos;
- scheduler, filas persistentes, workers e sender;
- `/admin metrics` de produto/comercial;
- source health/admin diagnostics;
- trilha v1/v2/dual-run de sources;
- backup/restore mínimo;
- leilões em piloto controlado.

Lacunas principais para lançamento público:

- billing automático Mercado Pago/webhook ou aprovação manual em 1 clique;
- teste de carga mínimo para beta/lançamento;
- operação beta/founders/growth.

## Estado atual de leilões

- Leilões não são mais apenas POC admin-only.
- Usuário pode optar por leilões por busca (`include_auctions`).
- Admin controla sources, elegibilidade e categorias permitidas.
- No piloto, apenas `car` deve chegar ao usuário; motos/caminhões/pesados/imóveis/outros ficam bloqueados por padrão.
- Scheduler de leilões pode rodar em dry-run automático; envio real automático continua bloqueado via comando admin nesta fase (`dry_run=false` não é permitido pelo comando de settings).
- Qualquer alerta user-facing de leilão deve conter disclosure visível antes do CTA/link: `Lance não é preço final.` e orientação sobre edital, taxas/comissão, documentação e vistoria.

## UX e copy user-facing

- Use `Garagem Alvo` como nome público em qualquer copy para usuário.
- Não exponha scheduler, filas, scraping, backoff, source internals ou detalhes operacionais ao usuário comum.
- Digest semanal deve transformar silêncio em evidência de monitoramento, especialmente quando não há anúncios ativos.
- Contexto de raridade/frequência em alerta só deve aparecer com amostra mínima confiável; não invente precisão estatística.
- Copy pós-criação deve diferenciar: resultado imediato, varredura em andamento, ausência/fonte indisponível e falha de agendamento.
- Alertas de leilão devem deixar `Lance não é preço final.` visível antes da ação de abrir o leilão.

## Sources e WebMotors

- Sources tradicionais são DB-driven; o fato de existir plugin não significa source ativa em produção.
- WebMotors está tecnicamente implementada, mas despriorizada por bloqueio anti-bot/fingerprint PerimeterX. Não tratar como falha crítica global sem decisão explícita.
- TurboClass está habilitada por default como source HTTP/feed experimental em validação.
- V1→V2 é trilha técnica incremental; não fazer flip geral sem inventário/dual-run/paridade.

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
- Billing/Premium: hoje ainda é operacional/manual; não documentar como automático sem webhook implementado.

## Ordem de leitura recomendada

1. `README.md`
2. `docs/README.md`
3. `docs/USER_FLOWS.md`
4. `docs/LLM_CONTEXT.md`
5. `docs/ARCHITECTURE.md`
6. `docs/PROJECT_GUIDELINE.md`
7. `docs/AUCTION_RUNTIME.md`
8. `docs/OPERATIONS_RUNBOOK.md`
9. `docs/LEGACY_INVENTORY.md`
10. Código: `app/bot/`, `app/scheduler/`, `app/services/`, `app/sources/`, `app/models/`
