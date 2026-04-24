# Backup / Restore operacional mínimo

Data: 2026-04-24.
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

## Backup
```bash
python scripts/backup_core_data.py --output backup_core.json
```

Com histórico de listings:
```bash
python scripts/backup_core_data.py --include-car-listings --car-listings-limit 10000 --output backup_core_with_listings.json
```

## Restore
Por padrão, roda em **dry-run** (sem escrita):
```bash
python scripts/restore_core_data.py --input backup_core.json
```

Aplicar restore:
```bash
python scripts/restore_core_data.py --input backup_core.json --apply
```

## Segurança e idempotência
- Scripts **não** imprimem secrets.
- `DATABASE_URL` é validada antes da execução.
- Restore usa `ON CONFLICT (id) DO NOTHING` (idempotente para linhas já existentes).
- Não há truncamento/overwrite automático.

## Limitações conhecidas
- Restore espera schema compatível com o backup.
- `car_listings` pode ser volumoso; por isso backup opcional com `--car-listings-limit`.

