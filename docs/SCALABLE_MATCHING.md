# Refactor: scalable matching with wishlist-token inverted index

## What this patch changes
- Adds `wishlist_tokens` table/model to build an inverted index (token -> wishlist).
- Matching no longer scans all wishlists. It:
  1) selects candidate wishlists by token overlap
  2) applies the existing match logic only on candidates

Wishlist remains SOURCE-AGNOSTIC.

## Migration
This repo snapshot doesn't include Alembic versions. Create the table in Postgres:

```sql
CREATE TABLE IF NOT EXISTS wishlist_tokens (
  id uuid PRIMARY KEY,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  wishlist_id uuid NOT NULL REFERENCES wishlists(id) ON DELETE RESTRICT,
  token text NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_wishlist_tokens_wishlist_token
  ON wishlist_tokens(wishlist_id, token);

CREATE INDEX IF NOT EXISTS ix_wishlist_tokens_token ON wishlist_tokens(token);
CREATE INDEX IF NOT EXISTS ix_wishlist_tokens_wishlist_id ON wishlist_tokens(wishlist_id);
CREATE INDEX IF NOT EXISTS ix_wishlist_tokens_token_wishlist ON wishlist_tokens(token, wishlist_id);
```

## Reindex
After deploy, run a one-off script in a python shell or create an admin command:

```py
from app.db.session import SessionLocal
from app.services.wishlist_tokens_service import rebuild_tokens_for_all_active_wishlists

with SessionLocal() as db:
    total = rebuild_tokens_for_all_active_wishlists(db)
    print("reindexed", total)
```

## Metrics
Scheduler pipeline summary now includes:
- `matching.candidates_p50`
- `matching.candidates_p95`
- `matching.wishlists_loaded`
