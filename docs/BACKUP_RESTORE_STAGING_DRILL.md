# Ensaio controlado de backup/restore em staging

Data de referência: 2026-04-25.

> **Aviso crítico:** nunca aplicar `restore --apply` em produção com banco existente.

## Objetivo
Executar um ensaio operacional controlado, sem impacto destrutivo em produção, cobrindo:
1. backup real no ambiente de origem;
2. validação de arquivo com `validate_core_backup.py`;
3. restore `dry-run` em staging;
4. restore real apenas em staging com base vazia;
5. reexecução de restore apply para validar idempotência;
6. comparação de contagens backup vs banco restaurado;
7. coleta de evidências do exercício.

## Pré-requisitos
- Ambiente de origem e staging com PostgreSQL/Supabase.
- `DATABASE_URL` apontando explicitamente para o ambiente correto em cada etapa.
- Banco de staging vazio (ou schema recém-provisionado sem dados core).
- Python com dependências do projeto.
- Acesso para salvar artefatos em armazenamento privado.

## Variáveis esperadas
- `DATABASE_URL` (origem para backup, staging para restore/compare).
- Caminho local para artefatos (ex.: `./artifacts/backup_drill_YYYYMMDD`).

## Artefatos obrigatórios
Salvar em pasta dedicada por ensaio:
- `backup_core_*.json`
- `validate.log`
- `restore_dry_run.log`
- `restore_apply_1.log`
- `restore_apply_2.log`
- `compare_counts.log`
- `drill_notes.md` (responsável, horário, conclusões)

## Procedimento passo a passo

### 1) Gerar backup real (origem)
```bash
mkdir -p artifacts/backup_drill_$(date -u +%Y%m%dT%H%M%SZ)
export DRILL_DIR=$(ls -dt artifacts/backup_drill_* | head -n1)

PYTHONPATH=. python scripts/backup_core_data.py \
  --output "$DRILL_DIR/backup_core.json"
```

Opcional (se desejar incluir histórico):
```bash
PYTHONPATH=. python scripts/backup_core_data.py \
  --include-car-listings \
  --car-listings-limit 10000 \
  --output "$DRILL_DIR/backup_core_with_listings.json"
```

### 2) Validar backup
```bash
PYTHONPATH=. python scripts/validate_core_backup.py \
  --input "$DRILL_DIR/backup_core.json" | tee "$DRILL_DIR/validate.log"
```
Critério mínimo: `Resultado: VÁLIDO` e exit code `0`.

### 3) Restore dry-run em staging
```bash
PYTHONPATH=. python scripts/restore_core_data.py \
  --input "$DRILL_DIR/backup_core.json" | tee "$DRILL_DIR/restore_dry_run.log"
```
Validar no log:
- `Modo: DRY-RUN`
- `Status final: success` ou `success_with_skips`
- sem erro estrutural impeditivo

### 4) Restore apply em staging (somente base vazia)
```bash
PYTHONPATH=. python scripts/restore_core_data.py \
  --input "$DRILL_DIR/backup_core.json" \
  --apply | tee "$DRILL_DIR/restore_apply_1.log"
```
Validar:
- `Modo: APPLY`
- resumo final por tabela
- `Status final: success` esperado na primeira aplicação em base vazia

### 5) Reaplicar restore para validar idempotência
```bash
PYTHONPATH=. python scripts/restore_core_data.py \
  --input "$DRILL_DIR/backup_core.json" \
  --apply | tee "$DRILL_DIR/restore_apply_2.log"
```
Validar:
- `Status final: success_with_skips` esperado
- aumento de `ignorados_conflito`
- sem sobrescrita de linhas existentes

### 6) Comparar contagens backup vs staging
```bash
PYTHONPATH=. python scripts/compare_core_backup_to_db.py \
  --input "$DRILL_DIR/backup_core.json" | tee "$DRILL_DIR/compare_counts.log"
```
Validar:
- saída por tabela com `expected`, `found`, `diff`
- `Resultado: OK (contagens compatíveis)`
- exit code `0`

## Interpretação dos resultados
- `success`: execução completa sem skips/erros relevantes.
- `success_with_skips`: execução concluída com conflitos esperados (`ON CONFLICT DO NOTHING`) e/ou FKs ausentes.
- `failed`: erro impeditivo.

## Critérios de sucesso do ensaio
1. Backup gerado e validado com sucesso.
2. Dry-run executado sem escrita e com relatório claro.
3. Primeiro `--apply` em staging vazio sem falhas.
4. Segundo `--apply` confirmando comportamento idempotente.
5. Comparação de contagens sem divergências relevantes.
6. Evidências completas salvas no diretório do ensaio.

## Rollback / limpeza
- Não há operação destrutiva prevista em produção.
- Em staging, se necessário, descartar base de ensaio e reprovisionar schema limpo.
- Remover artefatos locais apenas após armazenamento em local seguro.

## Riscos remanescentes
- Divergência de schema entre origem e staging pode gerar restore parcial.
- Backups com `car_listings` podem ser volumosos e lentos para restore.
- Diferenças operacionais de permissões/roles entre ambientes podem afetar apply.
