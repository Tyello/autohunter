# Incremental + Vendidos (TurboClass)

## Migração

Este patch adiciona:

- `source_url_cursors` (cursor incremental por `source+url`)
- `car_listings.is_sold` e `car_listings.sold_at`

Rode a migração:

```bash
alembic upgrade head
```

## Como usar

### 1) Incremental (TurboClass)

O TurboClass já vem com `incremental_enabled=true` por default (`source_configs.extra`).

Se sua row já existia, rode:

```text
/admin sources reset turboclass
```

(ou atualize `source_configs.extra` manualmente).

### 2) Vendidos

Habilite a source `turboclass_vendidos`:

```text
/admin sources enable turboclass_vendidos
```

Ela roda em modo feed (sem wishlists), varre `/vendidos` e marca `is_sold=true`.
O matching ignora itens vendidos.

## Telemetria

O `/admin sources` mostra `thumb=XX%` no `last ...` quando o `payload` do run traz `thumb_rate`.
