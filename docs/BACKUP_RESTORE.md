# Backup / Restore operacional mínimo

Data: 2026-04-25.  
Escopo: PostgreSQL/Supabase.

## Objetivo
Garantir recuperação mínima de dados core sem expor secrets e sem sobrescrita agressiva.

## Tabelas cobertas
- `users`
- `wishlists`
- `wishlist_filters`
- `wishlist_tracked_listings`
- opcional: `car_listings` (com limite)

## Pré-requisitos
- `DATABASE_URL` configurada no ambiente.
- URL deve ser PostgreSQL (`postgresql://...`).
- **SQLite não é suportado** para backup/restore.

## 1) Como gerar backup
Backup core:
```bash
PYTHONPATH=. python scripts/backup_core_data.py --output backup_core.json
```

Backup com histórico de listings:
```bash
PYTHONPATH=. python scripts/backup_core_data.py \
  --include-car-listings \
  --car-listings-limit 10000 \
  --output backup_core_with_listings.json
```

## 2) Onde guardar
- Armazenar em local seguro e versionado (bucket privado com retenção + criptografia).
- Manter cópia redundante fora do host de produção.
- Não compartilhar arquivos de backup em canais públicos.

## 3) Como validar backup
Validar estrutura + integridade referencial básica:
```bash
PYTHONPATH=. python scripts/validate_core_backup.py --input backup_core.json
```

Critério de sucesso:
- saída com `Resultado: VÁLIDO`
- exit code `0`

## 4) Como rodar restore dry-run
`dry-run` é padrão (sem escrita no banco):
```bash
PYTHONPATH=. python scripts/restore_core_data.py --input backup_core.json
```

O relatório de dry-run informa por tabela:
- `processar`
- `existentes` (já presentes no banco)
- `fk_ausente` (potencial falha de FK)
- `inseriveis` (estimativa)

Se houver incompatibilidade estrutural, o script sinaliza risco de restore parcial.

## 5) Como aplicar restore real em ambiente novo
Somente com flag explícita `--apply`:
```bash
PYTHONPATH=. python scripts/restore_core_data.py --input backup_core.json --apply
```

Comportamento:
- inserção com `ON CONFLICT (id) DO NOTHING`
- sem truncamento
- sem overwrite silencioso

## 6) Como validar contagens após restore
- Comparar `meta.table_row_counts` do backup com contagens no banco destino.
- Executar queries por tabela (`users`, `wishlists`, `wishlist_filters`, `wishlist_tracked_listings` e, se aplicável, `car_listings`).
- Reexecutar `restore --apply`: o esperado é alta taxa de `skipped` e baixa/zero de `inserted` (idempotência).

## 7) O que nunca fazer em produção
- Não rodar restore com `--apply` sem dry-run prévio.
- Não usar backup não validado.
- Não expor `DATABASE_URL`/tokens em logs, tickets ou chat.
- Não rodar restore em base de produção ativa sem janela e plano de rollback.

## 8) Checklist de recuperação
1. Confirmar ambiente alvo (não-produção para ensaio).
2. Confirmar `DATABASE_URL` PostgreSQL/Supabase.
3. Gerar backup.
4. Validar com `validate_core_backup.py`.
5. Rodar `restore_core_data.py` em dry-run.
6. Revisar riscos/compatibilidade reportados.
7. Aplicar restore com `--apply` somente se aprovado.
8. Validar contagens pós-restore.
9. Registrar evidências (comandos, logs resumidos, checks).

## Segurança e idempotência
- Scripts **não** imprimem secrets.
- `DATABASE_URL` é validada antes da execução.
- Restore usa `ON CONFLICT (id) DO NOTHING` (idempotente para linhas já existentes).
- Não há truncamento/overwrite automático.

## Limitações conhecidas
- Restore assume schema compatível com o backup.
- Dry-run fornece estimativa operacional; resultado final depende de constraints e tipos do banco alvo.
- `car_listings` pode ser volumoso; por isso backup opcional com `--car-listings-limit`.
