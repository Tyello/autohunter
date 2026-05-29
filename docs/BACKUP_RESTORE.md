# Backup / Restore operacional mínimo

Data: 2026-05-25.  
Escopo: PostgreSQL/Supabase + operação Raspberry Pi 4.

## Objetivo
Fechar a lacuna operacional de backup diário real do banco com `pg_dump`, mantendo restore manual e validável.

## Resumo rápido
- Backup diário em cron: `scripts/backup_db.sh` (dump completo `.sql.gz`).
- Verificação opcional de frescor: `scripts/check_latest_backup.sh`.
- Inspeção segura de dump SQL: `scripts/inspect_backup_dump.py`.
- Geração de restore seletivo core: `scripts/extract_core_restore_sql.py`.
- Restore permanece **manual** e **potencialmente destrutivo**.
- Backup core em JSON continua disponível para drill/table-level (`scripts/backup_core_data.py`).

## Regra de ouro para Supabase existente

> **Nunca aplique um dump completo `.sql.gz` diretamente em uma base Supabase existente.**
>
> O comando abaixo é inseguro contra produção/staging já provisionados e não deve ser usado para recuperar tabelas core dentro de uma base existente:
>
> ```bash
> gunzip -c /var/backups/autohunter/autohunter_YYYYmmdd_HHMMSS.sql.gz | psql "$DATABASE_URL"
> ```

Motivo: o dump completo de `pg_dump` contém DDL e dados de vários schemas. Em uma base Supabase existente, ele pode tentar recriar schemas/tabelas/índices já existentes, tocar schemas gerenciados (`auth`, `storage`, `extensions` etc.), gerar erros de permissão, duplicar PK/unique, falhar em FKs e ainda assim inserir parte dos dados antes de parar ou continuar com ruído.

Regras operacionais:

- Restore completo de `.sql.gz` só deve ser feito em banco vazio/staging criado para esse fim.
- Em produção existente, use restore seletivo de tabelas críticas com SQL gerado por `scripts/extract_core_restore_sql.py`.
- Antes de qualquer restore, pare `autohunter-bot` e `autohunter-scheduler` e mantenha-os parados até a validação final.
- Antes de qualquer restore, gere um dump do estado atual da base alvo.
- Antes de aplicar, valide o conteúdo do backup com `scripts/inspect_backup_dump.py`.
- Depois de aplicar, valide contagens, FKs órfãs, notificações antigas em fila, índice operacional de `scrape_jobs` e `alembic_version`.

## Classificação de dados (prioridade operacional)

### 1) Críticas para recuperação
- `users`
- `wishlists`
- `wishlist_filters`
- `plans`, `subscriptions`, `accounts`, `account_members`
- `wishlist_tokens`, `user_digest_preferences`
- `app_kv` (config runtime, incluindo settings operacionais)
- `source_configs`, `source_states` (estado operacional das sources)
- `wishlist_tracked_listings`

### 2) Importantes para evitar renotificação/perda de histórico
- `notifications`
- `car_listings`
- `wishlist_listing_activity`
- `wishlist_tracked_listings` (também crítica para continuidade)
- `source_url_cursors` (evita reprocessamento agressivo em alguns fluxos)

### 3) Operacionais/descartáveis (reconstruíveis)
- `system_logs`
- `telemetry_events`
- `source_runs`
- `scrape_jobs`
- artefatos temporários/caches de operação

> Nesta PR, a estratégia escolhida é **backup completo do banco** via `pg_dump` (mais seguro para recuperação mínima imediata).

## Variáveis de ambiente

### `scripts/backup_db.sh`
- `DATABASE_URL` (**obrigatória**)
- `AUTOHUNTER_BACKUP_DIR` (default: `/var/backups/autohunter`)
- `AUTOHUNTER_BACKUP_RETENTION_DAYS` (default: `14`; `<=0` desativa limpeza)
- `AUTOHUNTER_ENV_FILE` (opcional, aponta para arquivo env carregado antes da validação)

### Como o script encontra `DATABASE_URL` no cron
Antes de validar `DATABASE_URL`, o script tenta carregar variáveis (se o arquivo existir) nesta ordem:
1. `AUTOHUNTER_ENV_FILE`
2. `/etc/default/autohunter`
3. `/home/autohunter/autohunter/.env`
4. `./.env`

Precedência adotada:
- variáveis já exportadas no ambiente atual **não são sobrescritas** por valores dos arquivos;
- se nenhum arquivo existir, o script continua e falha apenas se `DATABASE_URL` ainda estiver ausente.

### `scripts/check_latest_backup.sh`
- `AUTOHUNTER_BACKUP_DIR` (default: `/var/backups/autohunter`)
- `AUTOHUNTER_BACKUP_MAX_AGE_HOURS` (default: `30`)

### `/admin health` / `BackupHealthService`
- `AUTOHUNTER_BACKUP_DIR` (default: `/var/backups/autohunter`)
- `AUTOHUNTER_BACKUP_MAX_AGE_HOURS` (default: `30`)
- `AUTOHUNTER_BACKUP_MIN_SIZE_BYTES` (default: `262144`)
- `AUTOHUNTER_BACKUP_VALIDATE_CRITICAL_TABLES` (default: `true`)
- `AUTOHUNTER_BACKUP_MIN_USERS` (default: `1`)
- `AUTOHUNTER_BACKUP_MIN_WISHLISTS` (default: `1`)
- `AUTOHUNTER_BACKUP_MIN_SOURCE_CONFIGS` (default: `1`)

## Recomendação para Raspberry Pi (cron)
Opção recomendada:
1. Criar `/etc/default/autohunter` com permissões restritas.
2. Definir no arquivo pelo menos:
   - `DATABASE_URL=postgresql://...`
   - `AUTOHUNTER_BACKUP_DIR=/var/backups/autohunter`

Alternativa:
- usar `AUTOHUNTER_ENV_FILE` apontando para um arquivo seguro (fora do repo).

Permissões recomendadas:
- arquivo de env não deve ser público (ex.: `chmod 600 /etc/default/autohunter`);
- diretório de backup deve ser restrito ao usuário operacional (o script já tenta `chmod 700`).

## Como rodar backup manual
```bash
DATABASE_URL='postgresql://user:<redacted>@host:5432/autohunter' \
AUTOHUNTER_BACKUP_DIR='/var/backups/autohunter' \
bash scripts/backup_db.sh
```

Comportamento esperado:
- gera `autohunter_YYYYmmdd_HHMMSS.sql.gz` em UTC;
- usa arquivo temporário e só finaliza no sucesso;
- imprime caminho final e tamanho;
- retorna exit code `!= 0` em falha.

## Como testar exatamente como o cron
```bash
sudo -u autohunter env -i AUTOHUNTER_ENV_FILE=/etc/default/autohunter /home/autohunter/autohunter/scripts/backup_db.sh
```

## Retenção de backups
- O script remove apenas `autohunter_*.sql.gz` do diretório configurado.
- Nunca faz limpeza fora de `AUTOHUNTER_BACKUP_DIR`.
- Para manter tudo:
```bash
AUTOHUNTER_BACKUP_RETENTION_DAYS=0 bash scripts/backup_db.sh
```

## Como validar se backup está recente
```bash
AUTOHUNTER_BACKUP_DIR='/var/backups/autohunter' \
AUTOHUNTER_BACKUP_MAX_AGE_HOURS=30 \
bash scripts/check_latest_backup.sh
```

Exit codes:
- `0`: existe backup recente
- `1`: não existe backup (ou diretório ausente)
- `2`: existe backup, mas velho demais

## Inspecionar backup SQL sem extrair e sem banco

Use a ferramenta de inspeção antes de qualquer restore. Ela lê o `.sql.gz` em streaming, não extrai permanentemente, não conecta no banco, não lê `.env` e não imprime `DATABASE_URL`.

```bash
python scripts/inspect_backup_dump.py /var/backups/autohunter/autohunter_YYYYmmdd_HHMMSS.sql.gz
```

Ela reporta tamanho e contagens dos blocos `COPY public.<tabela>` para:

- `users`
- `accounts`
- `account_members`
- `wishlists`
- `wishlist_filters`
- `wishlist_tokens`
- `wishlist_tracked_listings`
- `wishlist_listing_activity`
- `notifications`
- `source_configs`
- `source_states`
- `scrape_jobs`
- `source_runs`

Exit codes:

- `0`: dump legível e `users`, `wishlists`, `source_configs` não vazios.
- `1`: dump legível, mas algum gate crítico falhou (`users=0`, `wishlists=0` ou `source_configs=0`).
- `2`: arquivo ausente/ilegível/gzip inválido/dump truncado.

## Restore completo de dump SQL: somente banco vazio/staging

> **Atenção crítica:** restore completo é destrutivo e só é aceitável em banco vazio/staging. Não use contra produção existente.

1) Criar banco de destino vazio (preferencialmente staging primeiro).  
2) Validar conexão alvo com uma URL explicitamente redigida/conferida, nunca colada de logs.
3) Restaurar no banco vazio:
```bash
gunzip -c /var/backups/autohunter/autohunter_YYYYmmdd_HHMMSS.sql.gz \
  | psql 'postgresql://user:<redacted>@host:5432/autohunter_restore'
```
4) Verificar contagens e migrations no banco restaurado.

## Restore seletivo core em produção existente

Use este caminho para recuperar `users`/`wishlists` e tabelas dependentes em uma base Supabase já existente.

### Antes

1. Declarar janela operacional e responsável pela execução.
2. Parar serviços e confirmar que permanecem parados:
   ```bash
   sudo systemctl stop autohunter-bot autohunter-scheduler
   sudo systemctl is-active autohunter-bot autohunter-scheduler
   ```
3. Gerar dump do estado atual da base alvo antes de qualquer limpeza/restore:
   ```bash
   AUTOHUNTER_BACKUP_DIR=/var/backups/autohunter/pre_restore_$(date -u +%Y%m%d_%H%M%S) \
     bash scripts/backup_db.sh
   ```
4. Inspecionar o backup candidato:
   ```bash
   python scripts/inspect_backup_dump.py /var/backups/autohunter/autohunter_YYYYmmdd_HHMMSS.sql.gz
   ```
5. Gerar SQL seletivo e revisar antes de aplicar:
   ```bash
   python scripts/extract_core_restore_sql.py \
     /var/backups/autohunter/autohunter_YYYYmmdd_HHMMSS.sql.gz \
     --output /tmp/autohunter_core_restore.sql
   sed -n '1,120p' /tmp/autohunter_core_restore.sql
   ```

O SQL gerado contém apenas `COPY public.<tabela>` das tabelas permitidas, em ordem segura:

1. `users`
2. `account_members`
3. `user_digest_preferences`
4. `wishlists`
5. `wishlist_filters`
6. `wishlist_tokens`
7. `wishlist_tracked_listings`
8. `wishlist_listing_activity`
9. `notifications`

### Limpeza controlada antes do restore seletivo

Não existe script que apague dados de produção automaticamente. Se for necessário substituir o core atual pelo core do backup, execute manualmente, dentro de transação, somente depois de backup pré-restore e revisão por operador.

Ordem segura de limpeza:

```sql
BEGIN;
DELETE FROM account_members;
DELETE FROM user_digest_preferences;
DELETE FROM notifications;
DELETE FROM wishlist_tracked_listings;
DELETE FROM wishlist_tokens;
DELETE FROM wishlist_listing_activity;
DELETE FROM wishlist_filters;
DELETE FROM wishlists;
DELETE FROM users;
-- COMMIT somente após revisar o impacto nesta sessão.
-- ROLLBACK se qualquer contagem/escopo estiver errado.
COMMIT;
```

Não limpar neste procedimento:

- `source_configs`
- `source_states`
- `scrape_jobs`
- `source_runs`
- `car_listings`
- `telemetry_events`
- `system_logs`
- `app_kv`
- `alembic_version`

### Durante

1. Confirmar novamente que serviços continuam parados.
2. Aplicar somente o SQL seletivo revisado:
   ```bash
   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f /tmp/autohunter_core_restore.sql
   ```
3. Se ocorrer qualquer erro, pare, preserve logs, não religue serviços e avalie rollback/novo restore a partir do dump pré-restore.

### Depois: validação pós-restore obrigatória

Serviços ainda devem estar parados durante estas validações.

Contagens core:

```sql
SELECT 'users' AS table_name, COUNT(*) FROM users
UNION ALL SELECT 'wishlists', COUNT(*) FROM wishlists
UNION ALL SELECT 'wishlist_filters', COUNT(*) FROM wishlist_filters
UNION ALL SELECT 'wishlist_tokens', COUNT(*) FROM wishlist_tokens
UNION ALL SELECT 'wishlist_tracked_listings', COUNT(*) FROM wishlist_tracked_listings
UNION ALL SELECT 'wishlist_listing_activity', COUNT(*) FROM wishlist_listing_activity
UNION ALL SELECT 'notifications', COUNT(*) FROM notifications
ORDER BY table_name;
```

Checks de FKs órfãs:

```sql
SELECT 'wishlists_without_user' AS check_name, COUNT(*)
FROM wishlists w
LEFT JOIN users u ON u.id = w.user_id
WHERE u.id IS NULL
UNION ALL
SELECT 'filters_without_wishlist', COUNT(*)
FROM wishlist_filters f
LEFT JOIN wishlists w ON w.id = f.wishlist_id
WHERE w.id IS NULL
UNION ALL
SELECT 'tokens_without_wishlist', COUNT(*)
FROM wishlist_tokens t
LEFT JOIN wishlists w ON w.id = t.wishlist_id
WHERE w.id IS NULL
UNION ALL
SELECT 'tracked_without_wishlist', COUNT(*)
FROM wishlist_tracked_listings tr
LEFT JOIN wishlists w ON w.id = tr.wishlist_id
WHERE w.id IS NULL
UNION ALL
SELECT 'activity_without_wishlist', COUNT(*)
FROM wishlist_listing_activity a
LEFT JOIN wishlists w ON w.id = a.wishlist_id
WHERE w.id IS NULL
UNION ALL
SELECT 'notifications_without_user', COUNT(*)
FROM notifications n
LEFT JOIN users u ON u.id = n.user_id
WHERE n.user_id IS NOT NULL AND u.id IS NULL
UNION ALL
SELECT 'notifications_without_wishlist', COUNT(*)
FROM notifications n
LEFT JOIN wishlists w ON w.id = n.wishlist_id
WHERE n.wishlist_id IS NOT NULL AND w.id IS NULL;
```

Notificações pendentes/queued antigas:

```sql
SELECT status, COUNT(*) AS total, MIN(created_at) AS oldest_created_at, MAX(created_at) AS newest_created_at
FROM notifications
WHERE status IN ('pending', 'queued')
GROUP BY status
ORDER BY status;
```

Migrations e índice operacional:

```sql
SELECT * FROM alembic_version ORDER BY version_num;

SELECT schemaname, tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'scrape_jobs'
ORDER BY indexname;
```

Critérios mínimos antes de religar:

- Contagens batem com o backup escolhido ou com a expectativa documentada do incidente.
- Todos os checks de órfãos retornam `0`.
- `alembic_version` tem exatamente uma linha esperada para o código em produção.
- O índice `uq_scrape_jobs_active_source_queue` aparece em `pg_indexes`.
- Não há volume inesperado de notificações `pending`/`queued` antigas que possa causar reenvio indevido.
- `autohunter-bot` e `autohunter-scheduler` ainda estão parados antes da decisão final de religar.

Só depois disso:

```bash
sudo systemctl start autohunter-scheduler autohunter-bot
sudo systemctl status autohunter-scheduler autohunter-bot --no-pager
```

## Raspberry Pi 4 / cron
Arquivo: `config/raspberry-pi/crontab`

Linha ativa:
```cron
0 2 * * * autohunter /home/autohunter/autohunter/scripts/backup_db.sh
```

Notas:
- garantir `pg_dump` instalado no host;
- garantir arquivo seguro de env para o cron (`/etc/default/autohunter` ou `AUTOHUNTER_ENV_FILE`);
- monitorar saída via logs do cron/journald;
- testar restauração em banco separado periodicamente.

## Drill operacional em staging
- Procedimento detalhado complementar: `docs/BACKUP_RESTORE_STAGING_DRILL.md`.
- O drill permanece obrigatório antes de qualquer restore em produção.

## Como verificar pelo Telegram/admin

Use o comando:

```text
/admin health
```

O painel de health inclui uma seção de backup com semáforo operacional, arquivo, idade, tamanho, contagens estimadas de tabelas críticas e motivo explícito de `FAIL`/`WARNING` quando houver.

Contrato atual:

- `OK` (`✅`): existe backup recente (idade `<= AUTOHUNTER_BACKUP_MAX_AGE_HOURS`) **e** o arquivo passa nos gates mínimos de qualidade.
- `WARNING` (`⚠️`): o arquivo passa nos gates mínimos de qualidade, mas está antigo (idade `> AUTOHUNTER_BACKUP_MAX_AGE_HOURS`) ou tem alerta não bloqueante em tabela crítica opcional vazia.
- `FAIL` (`❌`): diretório ausente, nenhum arquivo `autohunter_*.sql.gz`, gzip/dump ilegível, arquivo abaixo de `AUTOHUNTER_BACKUP_MIN_SIZE_BYTES`, ausência de `COPY public.<tabela>` para tabela crítica, ou contagem abaixo dos mínimos obrigatórios.

Tabelas críticas verificadas no dump SQL:

- `users`
- `wishlists`
- `wishlist_filters`
- `accounts`
- `account_members`
- `source_configs`

Gates bloqueantes por padrão:

- tamanho do último `autohunter_*.sql.gz` precisa ser `>= AUTOHUNTER_BACKUP_MIN_SIZE_BYTES`;
- `COPY public.users`, `COPY public.wishlists` e `COPY public.source_configs` precisam existir;
- `users >= AUTOHUNTER_BACKUP_MIN_USERS`;
- `wishlists >= AUTOHUNTER_BACKUP_MIN_WISHLISTS`;
- `source_configs >= AUTOHUNTER_BACKUP_MIN_SOURCE_CONFIGS`.

## Incidente 2026-05-28: backup recente, mas vazio/incompleto

Em 2026-05-28, um arquivo recente em `/var/backups/autohunter/autohunter_20260528_050001.sql.gz` apareceu como saudável apenas por idade, mas era inválido operacionalmente: tinha cerca de 156 KB e continha `users=0`, `wishlists=0`, `wishlist_filters=0`, `notifications=0` e `scrape_jobs=0`. O backup anterior saudável tinha cerca de 12 MB e continha `users=1`, `wishlists=8`, `wishlist_filters=11`, `notifications=156`, `source_configs=16` e `scrape_jobs=2591`.

A partir deste contrato, idade recente não basta. Um backup com `users=0`, `wishlists=0`, `source_configs=0` ou tamanho abaixo do threshold configurado deve aparecer como `❌ FAIL` no `/admin health`, mesmo que tenha acabado de ser gerado.

Próximos passos quando não estiver `OK`:

1. Verificar a seção `🗄 Backup` em `/admin health` e ler o motivo exato de `FAIL`/`WARNING`.
2. Rodar `bash scripts/check_latest_backup.sh` para diagnóstico rápido de frescor.
3. Validar o conteúdo do dump com `python scripts/inspect_backup_dump.py /var/backups/autohunter/autohunter_YYYYmmdd_HHMMSS.sql.gz` ou restaurar em staging para conferir contagens reais.
4. Verificar se o cron diário de backup está ativo.
5. Verificar `DATABASE_URL` do ambiente operacional usado pelo cron/script.
6. Verificar permissões e existência de `/var/backups/autohunter` (ou `AUTOHUNTER_BACKUP_DIR` configurado).

> Esta checagem é somente de observabilidade no admin/Telegram; não executa backup e não executa restore. As contagens são estimadas a partir dos blocos `COPY` do `pg_dump`; para confirmação definitiva, restaure em staging e rode `COUNT(*)`.


### Detalhe operacional da recuperação

O caminho inseguro tentado durante o incidente foi aplicar o dump completo saudável de 2026-05-27 diretamente na base Supabase existente. Isso gerou erros de schema já existente, permissões em schemas gerenciados, duplicidade de PK/unique, falhas de FK, inserções parciais e `alembic_version` temporariamente com duas linhas (`c0f1e2d3a4b5` e `e7a1c9f2b4d3`).

O caminho correto foi extrair apenas blocos `COPY public.<tabela>` críticos do backup saudável e aplicá-los em ordem de dependência, após limpeza controlada do core afetado. A partir deste runbook, o operador deve usar `scripts/inspect_backup_dump.py` e `scripts/extract_core_restore_sql.py`; não deve montar `awk`/`zcat` manualmente para recuperar `users`/`wishlists`.

### Checklist do incidente: antes, durante e depois

Antes:

- [ ] Confirmar impacto e escolher backup candidato pelo conteúdo, não apenas por data.
- [ ] Parar `autohunter-bot` e `autohunter-scheduler`.
- [ ] Gerar dump do estado atual da base alvo.
- [ ] Rodar `python scripts/inspect_backup_dump.py <backup.sql.gz>`.
- [ ] Gerar `python scripts/extract_core_restore_sql.py <backup.sql.gz> --output /tmp/autohunter_core_restore.sql`.
- [ ] Revisar que o SQL gerado contém apenas `COPY public.users`, dependentes de wishlist e `notifications`.

Durante:

- [ ] Manter serviços parados.
- [ ] Se necessário, executar limpeza controlada somente das tabelas core documentadas.
- [ ] Aplicar `/tmp/autohunter_core_restore.sql` com `psql -v ON_ERROR_STOP=1 -f`.
- [ ] Parar imediatamente se houver erro; não continuar com tentativas de dump completo.

Depois:

- [ ] Validar contagens core.
- [ ] Validar órfãos de FK.
- [ ] Validar notificações `pending`/`queued` antigas.
- [ ] Validar `SELECT * FROM alembic_version ORDER BY version_num;` com uma única linha.
- [ ] Validar presença de `uq_scrape_jobs_active_source_queue` em `pg_indexes`.
- [ ] Religação dos serviços só após aprovação explícita da validação.
