# Inventário de Legado e Compatibilidade — AutoHunter

Objetivo: separar com clareza o que parece oficial/ativo, o que é compatibilidade herdada e o que é suspeita de obsolescência **sem remoções automáticas**.

Classificações usadas:
- **Oficial / ativo**
- **Compatibilidade herdada / legado provável**
- **Suspeito de obsolescência**
- **Não remover sem validação**

> Fonte de verdade: código atual. Quando houver dúvida, ela é registrada explicitamente.

## Inventário

| Caminho | Classificação | Evidência observável | Risco de remover | Recomendação |
|---|---|---|---|---|
| `app/bot/run.py` | Oficial / ativo | Registra comandos principais do bot e inicia polling Telegram. | Alto | Manter como superfície principal de produto. |
| `app/scheduler/run.py` | Oficial / ativo | Agenda ticks por source, workers HTTP/browser, sender, monitor, digest, autopilot. | Alto | Tratar como núcleo operacional; mudanças só incrementais. |
| `app/services/source_execution_service.py` | Oficial / ativo | Runner central de source com due/backoff/elegibilidade/ingest/match/telemetry. | Alto | Evitar refactor massivo sem suite forte de testes. |
| `app/services/source_configs_service.py` + `app/models/source_config.py` | Oficial / ativo | Configuração runtime DB-driven; `ensure_source_configs` semeia defaults de plugin. | Alto | Preservar contrato DB-driven. |
| `app/models/source_state.py` | Oficial / ativo | Estado operacional por source (backoff, last_run, alert throttle). | Alto | Não remover campos sem migração/revisão operacional. |
| `app/models/scrape_job.py` + `app/services/scrape_jobs_service.py` | Oficial / ativo | Fila persistente com lock, retries e dedupe de job ativo. | Alto | Manter invariantes de fila. |
| `app/main.py` + `app/web/*` | Oficial / ativo (auxiliar) | FastAPI expõe health/listings/admin health e fluxo Facebook Agent. | Médio | Manter como superfície auxiliar; não promover como jornada principal sem decisão explícita. |
| `app/sources/builtins.py` | Oficial / ativo | Registry único com plugins de source atuais. | Alto | Usar como referência de “implementado no código”. |
| `app/sources/adapters/v1.py`, `app/sources/adapters/v2.py`, `app/sources/dual_run.py`, `app/sources/flags.py` | Compatibilidade herdada / legado provável | Pipeline suporta impl `v1`, `v2` e `dual` por flags. | Alto | Não remover; tratar como trilha de migração controlada. |
| `app/scrapers/*` e `app/scrapers/sources/*` (coexistência) | Compatibilidade herdada / legado provável | Há sobreposição de estrutura e bridges de adapter; coexistência explícita no código. | Médio/Alto | Consolidar apenas com validação de uso e cobertura. |
| `app/bot/run.py` (comentário “modo antigo continua”) + handlers wishlist antigos/novos | Compatibilidade herdada / legado provável | Comando `/wishlist` antigo convive com fluxo `wishlist_add` (UI nova). | Médio | Planejar sunset com métricas de uso antes de remover comandos antigos. |
| `app/web/routes_auth_facebook.py` rota `/auth/facebook/legacy` | Compatibilidade herdada / legado provável | Nome da rota e comportamento HTML simples indicam caminho legado ainda disponível. | Médio | Manter por compatibilidade; documentar como legado e monitorar uso. |
| `app/notifications/email.py`, `app/notifications/whatsapp.py`, `app/notifications/webhook.py` | Suspeito de obsolescência (ou uso opcional) | Existem módulos/campos de settings, mas caminho principal confirmado é Telegram sender. | Médio | Não remover sem confirmar uso em ambiente real; classificar como opcional/experimental. |
| `docs/PATCH_*.md`, `docs/diagnostico_handoff_2026-03-19.md`, `docs/projeto.md`, `docs/launch_plan.md` | Suspeito de obsolescência documental | Conteúdo histórico/migração/planejamento pode divergir do runtime atual. | Baixo (código) / Médio (onboarding errado) | Preservar como histórico, mas apontar `PROJECT_GUIDELINE.md` como documentação viva. |
| `app/services/admin_deploy_service.py`, `app/bot/admin_handlers_deploy.py` | Não remover sem validação | Fluxo de deploy/admin existe no runtime e pode ser crítico em operação real. | Alto | Manter até haver validação operacional explícita. |
| `app/scheduler/autopilot_job.py` + `app/services/autopilot_service.py` | Não remover sem validação | Jobs ligados no scheduler por default (`autopilot_enabled`). | Médio/Alto | Considerar parte da observabilidade operacional atual. |
| `app/scheduler/cleanup_job.py` | Não remover sem validação | Agendado por default para higiene de notificações. | Médio | Remoção pode causar crescimento de dados/filas. |
| `config/raspberry-pi/` e docs de Raspberry | Não remover sem validação | Indício de ambiente operacional específico suportado. | Médio | Preservar até confirmar estratégia de deploy final. |

## Marcação de depreciação aplicada no código (neste bloco)
- `app/web/routes_auth_facebook.py`: rota `/auth/facebook/legacy` recebeu comentário curto de “legacy path” para reduzir ambiguidade e evitar promoção acidental como fluxo novo.

## Regras práticas antes de qualquer remoção
1. Confirmar import/chamada e frequência de uso em logs/runs.
2. Confirmar dependência em comandos admin/operação.
3. Confirmar impacto em schema e dados históricos.
4. Definir rollback simples.

## Incertezas assumidas explicitamente
- Não foi feita leitura de métricas reais de uso (produção), então classificações “suspeito” são hipóteses conservadoras.
- Para canais de notificação além Telegram, o código existe; uso efetivo depende de configuração/ambiente.
