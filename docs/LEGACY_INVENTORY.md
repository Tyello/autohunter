# Inventário de Legado e Compatibilidade — AutoHunter

Objetivo: separar com clareza o que parece oficial/ativo, o que é compatibilidade herdada e o que é suspeita de obsolescência **sem remoções automáticas**.

Classificações usadas:

- **Oficial / ativo**
- **Compatibilidade herdada / legado provável**
- **Suspeito de obsolescência**
- **Histórico documental**
- **Não remover sem validação**

> Fonte de verdade: código atual + documentação viva (`README.md`, `docs/PROJECT_GUIDELINE.md`, `docs/AUCTION_RUNTIME.md`, `docs/OPERATIONS_RUNBOOK.md`).

## Inventário

| Caminho | Classificação | Evidência observável | Risco de remover | Recomendação |
|---|---|---|---|---|
| `app/bot/run.py` | Oficial / ativo | Registra comandos principais do bot e inicia polling Telegram. | Alto | Manter como superfície principal de produto. |
| `app/scheduler/run.py` | Oficial / ativo | Agenda ticks por source, workers HTTP/browser, sender, monitor, digest, autopilot e scheduler de leilões. | Alto | Tratar como núcleo operacional; mudanças só incrementais. |
| `app/services/source_execution_service.py` | Oficial / ativo | Runner central de source tradicional com due/backoff/elegibilidade/ingest/match/telemetry. | Alto | Evitar refactor massivo sem suite forte de testes. |
| `app/services/source_configs_service.py` + `app/models/source_config.py` | Oficial / ativo | Configuração runtime DB-driven; controla sources tradicionais e auction sources via `source_type`. | Alto | Preservar contrato DB-driven. |
| `app/services/auction_notification_settings_service.py` | Oficial / ativo | Config runtime de notificações de leilão em AppKV com fallback env e kill switch. | Alto | Não substituir por `.env` puro; manter comando admin e fallback. |
| `app/services/auction_notification_service.py` | Oficial / ativo | Monta alertas de leilão com gates de categoria, score, idade, bid, dedupe e limites. | Alto | Preservar gates antes de qualquer envio real. |
| `app/sources/auctions/registry.py` | Oficial / ativo | Registry técnico das sources de leilão e aliases. | Alto | Não duplicar aliases em handlers/services. |
| `app/models/source_state.py` | Oficial / ativo | Estado operacional por source tradicional (backoff, last_run, alert throttle). | Alto | Não remover campos sem migração/revisão operacional. |
| `app/models/scrape_job.py` + `app/services/scrape_jobs_service.py` | Oficial / ativo | Fila persistente com lock, retries e dedupe de job ativo. | Alto | Manter invariantes de fila. |
| `app/main.py` + `app/web/*` | Oficial / ativo (auxiliar) | FastAPI expõe health/listings/admin health e fluxos auxiliares. | Médio | Manter como superfície auxiliar; não promover como jornada principal sem decisão explícita. |
| `app/sources/builtins.py` | Oficial / ativo | Registry de plugins de sources tradicionais. | Alto | Usar como referência de “implementado no código”. |
| `app/sources/adapters/v1.py`, `app/sources/adapters/v2.py`, `app/sources/dual_run.py`, `app/sources/flags.py` | Compatibilidade herdada / legado provável | Pipeline suporta impl `v1`, `v2` e `dual` por flags. | Alto | Não remover; tratar como trilha de migração controlada. |
| `app/scrapers/*` e `app/scrapers/sources/*` | Compatibilidade herdada / legado provável | Há sobreposição de estrutura e bridges de adapter. | Médio/Alto | Consolidar apenas com validação de uso e cobertura. |
| Handlers antigos de wishlist/busca | Compatibilidade herdada / legado provável | UX guiada convive com comandos rápidos/legados. | Médio | Planejar sunset com métricas de uso antes de remover. |
| `app/web/routes_auth_facebook.py` rota `/auth/facebook/legacy` | Compatibilidade herdada / legado provável | Nome da rota e comportamento HTML simples indicam caminho legado ainda disponível. | Médio | Manter por compatibilidade; monitorar uso. |
| `app/notifications/email.py`, `app/notifications/whatsapp.py`, `app/notifications/webhook.py` | Suspeito de obsolescência (ou uso opcional) | Caminho principal confirmado é Telegram sender. | Médio | Não remover sem confirmar uso em ambiente real. |
| `docs/PATCH_*.md`, `docs/diagnostico_handoff_*.md`, `docs/projeto.md`, `docs/launch_plan.md` | Histórico documental | Conteúdo histórico/migração/planejamento pode divergir do runtime atual. | Baixo código / Médio onboarding | Preservar como histórico; apontar docs vivos como fonte atual. |
| Blocos antigos de POC/admin-only de leilões em documentos históricos | Histórico documental | Leilões evoluíram para opt-in por wishlist + runtime settings + scheduler dry-run. | Médio onboarding | Usar `docs/AUCTION_RUNTIME.md` como referência atual. |
| `app/services/admin_deploy_service.py`, `app/bot/admin_handlers_deploy.py` | Não remover sem validação | Fluxo de deploy/admin existe no runtime e pode ser crítico. | Alto | Manter até validação operacional explícita. |
| `app/scheduler/autopilot_job.py` + `app/services/autopilot_service.py` | Não remover sem validação | Jobs ligados no scheduler por configuração. | Médio/Alto | Considerar parte da observabilidade operacional atual. |
| `app/scheduler/cleanup_job.py` e jobs de filesystem cleanup | Não remover sem validação | Higiene operacional de dados/cache/logs. | Médio | Remoção pode causar crescimento de dados/filas/disco. |
| `config/raspberry-pi/` | Não remover sem validação | Ambiente operacional suportado. | Médio | Preservar até confirmar estratégia de deploy final. |

## Regras práticas antes de qualquer remoção

1. Confirmar import/chamada e frequência de uso em logs/runs.
2. Confirmar dependência em comandos admin/operação.
3. Confirmar impacto em schema e dados históricos.
4. Definir rollback simples.
5. Para leilões, confirmar se a mudança afeta gates de opt-in/source/categoria/dry-run.

## Incertezas assumidas explicitamente

- Não foi feita leitura de métricas reais de produção neste inventário.
- Para canais de notificação além Telegram, o código existe; uso efetivo depende de configuração/ambiente.
- Documentos históricos podem conter decisões antigas de POC; estado atual deve ser conferido nos docs vivos e no código.

## Docs vivos atuais

- `README.md`
- `AGENTS.md`
- `docs/PROJECT_GUIDELINE.md`
- `docs/AUCTION_RUNTIME.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/BACKUP_RESTORE.md`
