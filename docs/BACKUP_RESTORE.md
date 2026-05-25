# Backup / Restore operacional mínimo

Data: 2026-05-25.  
Escopo: PostgreSQL/Supabase + operação Raspberry Pi 4.

## Objetivo
Fechar a lacuna operacional de backup diário real do banco com `pg_dump`, mantendo restore manual e validável.

## Resumo rápido
- Backup diário em cron: `scripts/backup_db.sh` (dump completo `.sql.gz`).
- Verificação opcional de frescor: `scripts/check_latest_backup.sh`.
- Restore permanece **manual** e **potencialmente destrutivo**.
- Backup core em JSON continua disponível para drill/table-level (`scripts/backup_core_data.py`).

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

## Restore manual (dump SQL)

> **Atenção crítica:** restore é destrutivo se aplicado em base errada. Não executar em produção sem snapshot/backup prévio e janela operacional.

1) Criar banco de destino vazio (preferencialmente staging primeiro).  
2) Validar conexão alvo em `DATABASE_URL`.  
3) Restaurar:
```bash
gunzip -c /var/backups/autohunter/autohunter_YYYYmmdd_HHMMSS.sql.gz \
  | psql 'postgresql://user:<redacted>@host:5432/autohunter_restore'
```
4) Verificar tabelas críticas pós-restore (exemplo):
```bash
psql 'postgresql://user:<redacted>@host:5432/autohunter_restore' -c "SELECT COUNT(*) FROM users;"
psql 'postgresql://user:<redacted>@host:5432/autohunter_restore' -c "SELECT COUNT(*) FROM wishlists;"
psql 'postgresql://user:<redacted>@host:5432/autohunter_restore' -c "SELECT COUNT(*) FROM wishlist_filters;"
psql 'postgresql://user:<redacted>@host:5432/autohunter_restore' -c "SELECT COUNT(*) FROM notifications;"
psql 'postgresql://user:<redacted>@host:5432/autohunter_restore' -c "SELECT COUNT(*) FROM car_listings;"
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

O painel de health agora inclui uma linha de backup com semáforo operacional:

- `OK` (`✅`): existe backup recente (idade `<= BACKUP_MAX_AGE_HOURS`).
- `WARNING` (`⚠️`): existe backup, mas está antigo (idade `> BACKUP_MAX_AGE_HOURS`).
- `FAIL` (`❌`): diretório ausente ou nenhum arquivo `autohunter_*.sql.gz` encontrado.

Próximos passos quando não estiver `OK`:

1. Rodar `bash scripts/check_latest_backup.sh` para diagnóstico rápido.
2. Verificar se o cron diário de backup está ativo.
3. Verificar `DATABASE_URL` do ambiente operacional usado pelo cron/script.
4. Verificar permissões e existência de `/var/backups/autohunter` (ou `BACKUP_DIR` configurado).

> Esta checagem é somente de observabilidade no admin/Telegram; não executa backup e não executa restore.
