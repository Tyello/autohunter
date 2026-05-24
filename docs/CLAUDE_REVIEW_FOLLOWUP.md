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
