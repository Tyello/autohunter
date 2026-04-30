# Claude Review Follow-up

## Entregue nesta tranche
- Correções de bugs aplicadas em `app/sources/normalize.py`, `app/services/wishlists_service.py` e `app/bot/handlers.py`.
- DRY aplicado para normalização textual (`app/core/text_norm.py`) e mapeamento de UFs/estados (`app/core/geo.py`).
- Normalização automotiva parcial com cobertura de transmissão e variantes de combustível GNV.
- `CarListing`/`CarListingOut` e migration preparados para os campos `doors`, `body_type` e `cross_source_fingerprint`.

## Pendências

### P0 — validação/migration
- Consolidar validação end-to-end de migrations em ambiente com cadeia completa e histórico homogêneo de revisions.

### P1 — filtros estruturados
- Filtros estruturados para KM, seller, body_type e doors.

### P1 — tracking/price_drop
- Tracking de preço e `price_drop` funcional.
- Cross-source dedupe funcional.

### P2 — score/digest/raridade
- `score_v2` automotivo.
- Digest semanal.
- Contexto de raridade.

### P3 — refactors grandes
- Refactor de `handlers_admin`.
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

