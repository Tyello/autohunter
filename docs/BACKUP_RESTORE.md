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
3. Validar o conteúdo do dump com `gunzip -c /var/backups/autohunter/autohunter_YYYYmmdd_HHMMSS.sql.gz | less` ou restaurar em staging para conferir contagens reais.
4. Verificar se o cron diário de backup está ativo.
5. Verificar `DATABASE_URL` do ambiente operacional usado pelo cron/script.
6. Verificar permissões e existência de `/var/backups/autohunter` (ou `AUTOHUNTER_BACKUP_DIR` configurado).

> Esta checagem é somente de observabilidade no admin/Telegram; não executa backup e não executa restore. As contagens são estimadas a partir dos blocos `COPY` do `pg_dump`; para confirmação definitiva, restaure em staging e rode `COUNT(*)`.
