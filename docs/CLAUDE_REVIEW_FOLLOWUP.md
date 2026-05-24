# Claude Review Follow-up

## Entregue nesta tranche
- Correções de bugs aplicadas em `app/sources/normalize.py`, `app/services/wishlists_service.py` e `app/bot/handlers.py`.
- DRY aplicado para normalização textual (`app/core/text_norm.py`) e mapeamento de UFs/estados (`app/core/geo.py`).
- Normalização automotiva parcial com cobertura de transmissão e variantes de combustível GNV.
- `CarListing`/`CarListingOut` e migration preparados para os campos `doors`, `body_type` e `cross_source_fingerprint`.

## Pendências

### P0 — validação/migration
- **Concluído:** validação end-to-end do schema PostgreSQL/Supabase executada com sucesso via `scripts/validate_postgres_schema.py`.
- Evidências registradas: conexão PostgreSQL OK, Alembic com head único `aa21b3c4d5e6`, banco em `aa21b3c4d5e6`, colunas críticas em `car_listings` presentes e índice partial `ix_notifications_user_sent_today` confirmado.
- Resultado da execução real: `OK=8, WARNING=0, FAIL=0`.
- Status atual: **sem pendência operacional P0 aberta para schema/migrations**.

### P1 — filtros estruturados
- Filtros estruturados para KM, seller, body_type e doors.

### P1 — tracking/price_drop
- **Concluído:** sync de tracking implementado com atualização incremental de preço/status usando os campos já existentes de `WishlistTrackedListing` (sem migration).
- **Concluído:** detecção + enfileiramento de alerta `price_drop` implementados com anti-duplicidade por preço e cooldown configurável.
- Cross-source dedupe funcional.

### P2 — score/digest/raridade
- `score_v2` automotivo.
- Digest semanal.
- Contexto de raridade.

### P3 — refactors grandes
- Refactor de `handlers_admin` **iniciado** com extração incremental e segura de helpers puros (parsing/formatting/labels/data-string) para módulo auxiliar, mantendo entrypoints e comportamento.
- Pendente: refactor completo de `handlers_admin` (decomposição maior por domínios de comando e integrações).
- Mitigação do `settings` como god object.

## Comandos guiados no Telegram

O AutoHunter tem muitos comandos e opções. Para reduzir fricção, vamos evoluir comandos principais para modo guiado com botões/menus e perguntas passo a passo, mantendo comandos rápidos para usuários avançados.

Escopo futuro:
- criar wishlist guiada;
- adicionar filtros guiados;
- listar/editar filtros por botões;
- rastrear anúncio por botão;
- gerenciar slots rastreados por botões;
- ativar/desativar notificações automáticas por botões;
- menu principal com ações mais comuns.

Diretriz:
- manter comandos atuais por compatibilidade;
- botões/guiado como caminho recomendado;
- não mover regra de negócio para handlers;
- handlers só orquestram serviços.

- Tracking/price_drop ganhou observabilidade admin via `/admin tracking` com diagnóstico operacional (contagens, status e pendências), sem alterar regra de negócio.

### Atualização P2 — Digest semanal
- **Fundação implementada (manual/admin):** criado `build_weekly_digest_for_user` em `app/services/weekly_digest_service.py` e renderer `render_weekly_digest` em `app/bot/weekly_digest_renderer.py`.
- **Comando admin manual:** `/admin digest user <telegram_chat_id> [dias]` (janela limitada entre 1 e 30, default 7).
- **Listagem de candidatos admin:** `/admin digest candidates [dias] [limite]` para preview operacional em lote (somente usuários com `notifications.status='sent'` na janela).
- **Status da pendência:** parcialmente concluída com execução segura/read-only e sem broadcast.
- **Ainda pendente (fora deste PR):** scheduler automático, envio recorrente para usuário final, preferências opt-in/opt-out.


## P2 — Weekly Digest Preferences

- Implementado: opt-in/opt-out admin para digest semanal com tabela dedicada `user_digest_preferences`.
- Implementado: configuração básica (`digest_days`, `digest_limit`) e status consultável por admin.
- Implementado: filtro opcional `only_enabled` em candidates para base de scheduler futuro.
- Pendente (fora deste PR): scheduler automático, envio recorrente real, comando de autoatendimento para usuário final.

### P2 — Weekly Digest scheduler controlado (opt-in)

- Implementado `app/scheduler/weekly_digest_job.py` com execução segura (dry-run/live), batch/limite, logs e atualização de `last_digest_sent_at` só após envio bem-sucedido.
- Implementado comando admin manual `/admin digest run [dry|live]` com gate forte para live (`weekly_digest_job_enabled=true`).
- Garantia explícita: envio restrito a usuários com `weekly_digest_enabled=true` e elegibilidade ativa/chat/janela mínima por `digest_days`.

Pendências mantidas para próximas PRs:
- integração com cron/systemd externo no Raspberry (se desejado operacionalmente);
- contexto de raridade avançado no digest (se desejado e ainda não implementado).

Atualização de status:
- comando de autoatendimento do usuário final (`/digest`) implementado.


### Atualização P2.1 — Refinamento de conteúdo do digest
- Implementado enriquecimento do payload do digest com `by_source`, `by_reason`, `recent_alerts`, metadados de oportunidade (ano/km/localização, reason e score_breakdown resumido quando presente).
- Renderer atualizado com resumo mais legível, top oportunidades, quedas de preço e buscas com mais alertas, incluindo formatação BRL/km/localização e empty state útil ao usuário.
- Mantido escopo: sem mudanças em scheduler, opt-in, preferências ou regras de envio.
