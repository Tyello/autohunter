# Guardrails de banco para dados core de usuário/wishlist

Em 2026-05-28 houve perda seletiva de dados críticos do produto. Esta página documenta a proteção adicionada para impedir que `DELETE`/`TRUNCATE` acidentais passem silenciosamente no banco normal.

## Tabelas protegidas

As tabelas abaixo representam identidade, buscas, filtros, rastreamento e fila/histórico de comunicação do usuário. Elas não devem ser limpas por scripts genéricos, restore seletivo mal parametrizado ou rotinas operacionais sem revisão explícita:

- `users`
- `wishlists`
- `wishlist_filters`
- `wishlist_tokens`
- `wishlist_tracked_listings`
- `wishlist_listing_activity`
- `notifications`
- `account_members`
- `user_digest_preferences`

A PR não protege `source_configs`, `source_states`, `scrape_jobs`, `source_runs` ou tabelas operacionais de scraping. O guardrail reduz o risco de acidente operacional, mas não substitui role least-privilege, backup validado, revisão de scripts e runbooks de restore.

## Como o guardrail funciona

A migration Alembic `5c8f1a2b3d4e_core_data_delete_guardrails.py` cria a função PostgreSQL `public.prevent_core_data_delete_without_guard()` e instala dois triggers por tabela protegida:

- `BEFORE DELETE FOR EACH STATEMENT`
- `BEFORE TRUNCATE FOR EACH STATEMENT`

A função consulta a variável de sessão/transação `app.allow_core_data_delete`. Se o valor não for exatamente `on`, a operação é bloqueada com erro claro:

```sql
Blocked DELETE on protected core table public.users. Set app.allow_core_data_delete=on inside an explicit break-glass transaction to proceed.
```

`SELECT`, `INSERT` e `UPDATE` continuam permitidos. A proteção é deliberadamente no banco, não apenas na aplicação, para cobrir scripts, shells SQL, jobs administrativos e erros de restore.

## Break-glass para operação destrutiva controlada

Use apenas em manutenção revisada, preferencialmente com uma transação manual curta, backup validado e escopo explícito.

Exemplo recomendado:

```sql
BEGIN;
SET LOCAL app.allow_core_data_delete = 'on';

-- operação destrutiva revisada e limitada
DELETE FROM wishlists
WHERE id = '00000000-0000-0000-0000-000000000000';

COMMIT;
```

Se for necessário executar múltiplos comandos no mesmo bloco, mantenha todos dentro da transação e registre o motivo no runbook/incidente. Evite `SET app.allow_core_data_delete = 'on'` fora de transação porque o valor pode permanecer ativo durante a sessão.

## Usuário runtime do banco

O runtime atual não deve usar `postgres` em `DATABASE_URL`. `postgres` é superusuário/poderoso demais para bot, scheduler, workers e API auxiliar. O usuário recomendado é uma role dedicada, por exemplo `autohunter_app`, com privilégios mínimos para executar o produto. Enquanto o runtime continuar conectado como `postgres`, `/health`, `/admin/health` e `/admin health` devem aparecer em `WARNING` com a recomendação de migrar para `autohunter_app`.

Checklist inicial para criar role least-privilege no Supabase/PostgreSQL:

1. Criar role de runtime sem superuser:
   ```sql
   CREATE ROLE autohunter_app LOGIN PASSWORD '<senha-forte>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
   ```
2. Conceder acesso ao schema usado pela aplicação:
   ```sql
   GRANT USAGE ON SCHEMA public TO autohunter_app;
   ```
3. Conceder privilégios DML necessários nas tabelas da aplicação:
   ```sql
   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO autohunter_app;
   GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO autohunter_app;
   ```
4. Ajustar privilégios padrão para migrations futuras:
   ```sql
   ALTER DEFAULT PRIVILEGES IN SCHEMA public
   GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO autohunter_app;

   ALTER DEFAULT PRIVILEGES IN SCHEMA public
   GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO autohunter_app;
   ```
5. Manter migrations/Alembic em uma role operacional separada e mais privilegiada, não no runtime 24/7.
6. Atualizar `DATABASE_URL` dos serviços runtime para a nova role.
7. Conferir `/admin health` ou `/admin/health`: deve deixar de mostrar o warning `runtime usando role postgres; recomendado usar role autohunter_app least-privilege`.

> Observação Supabase: confirme no painel/SQL editor quais grants extras são exigidos pelo projeto (extensions, schemas adicionais, RLS/policies). A aplicação AutoHunter usa configuração operacional DB-driven, então o runtime precisa DML normal, mas não deve precisar poderes de owner/superuser.

## Inventário atual de hard delete no código

Mapeamento feito nesta PR com `rg -n "delete\(|delete\s+from|TRUNCATE|truncate\(|session\.delete|\.delete\(" app tests scripts migrations -S`:

### Fluxos normais do produto

- `app/services/wishlists_service.py`
  - `remove_filter`: agora faz soft delete (`wishlist_filters.is_active=false`).
  - `remove_wishlist` / `remove_all_wishlists`: agora fazem soft delete (`wishlists.deleted_at`, `wishlists.is_active=false`) e inativam filtros/rastreamentos ativos sem apagar histórico. O log `wishlist_delete_explicit` foi preservado para auditoria.
- `app/services/wishlist_tokens_service.py`
  - `rebuild_tokens_for_wishlist`: agora insere apenas tokens faltantes e não executa `DELETE` no runtime normal.
- `app/services/wishlist_tracking_service.py`
  - `remove_tracked_listing`: agora faz soft delete (`wishlist_tracked_listings.is_active=false`).
- `app/services/notifications_cleanup_service.py`
  - agora roda em modo `report_only_core_data_guardrail`: conta candidatas de retenção, mas não apaga `notifications` no runtime normal.

### Administrativo/testes/migrations

- `migrations/versions/7b9e1c2d3f4a_remove_legacy_plans_pro_ultra_paid.py`: remove planos legados (`plans`), fora do escopo core desta PR.
- `tests/test_backup_restore_scripts.py`: valida que scripts de restore não usam `TRUNCATE public.users` no fluxo seguro.
- `tests/test_delete_safety.py`: testes de restrição/ausência de cascade e remoção explícita.
- Testes/admin de leilões podem apagar configs de teste (`source_configs`), fora do escopo core desta PR.

## Soft delete no runtime normal

Para não quebrar a UX normal do bot depois da instalação dos triggers:

- remoção user-facing de wishlist passa a marcar `wishlists.deleted_at` e `wishlists.is_active=false`;
- remoção de filtros marca `wishlist_filters.is_active=false`;
- remoção de rastreamentos marca `wishlist_tracked_listings.is_active=false`;
- as constraints únicas de filtros/rastreamentos passam a ser índices parciais apenas para linhas ativas;
- rebuild de `wishlist_tokens` deixa de executar `DELETE` e apenas insere tokens faltantes.

TODO remanescente: se houver necessidade futura de reduzir fisicamente `notifications` ou remover tokens obsoletos, tratar como manutenção controlada com break-glass, backup validado e escopo SQL explícito.

## Observação sobre downgrade

A migration troca constraints únicas físicas de filtros/rastreamentos por índices parciais apenas para linhas ativas. Depois que o runtime criar duplicatas inativas via soft delete, um downgrade que recrie as constraints antigas pode falhar até que duplicatas inativas sejam revisadas/limpas manualmente. Trate esse downgrade como operação de manutenção com backup validado e plano de limpeza explícito.
