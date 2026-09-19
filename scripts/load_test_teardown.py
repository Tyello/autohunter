"""
Load-test teardown: remove usuarios sinteticos criados por
scripts/load_test_seed.py (identificados pela faixa reservada de
telegram_chat_id < LOAD_TEST_CHAT_ID_BASE) e todos os dados dependentes.

Dry-run por padrao (so conta candidatos); usar --apply para executar.

As tabelas de usuario/wishlist sao protegidas por um trigger de guardrail
(migration 5c8f1a2b3d4e_core_data_delete_guardrails) que bloqueia DELETE sem
`SET LOCAL app.allow_core_data_delete='on'` na mesma transacao — mesmo padrao
break-glass ja usado em scripts/cleanup_operational_data.py.

Uso:
    python scripts/load_test_teardown.py            # dry-run
    python scripts/load_test_teardown.py --apply     # remove de verdade
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from app.core.settings import settings
from app.db.session import SessionLocal
from scripts.load_test_seed import LOAD_TEST_CHAT_ID_BASE

# Ordem de delecao respeita as FKs RESTRICT: filhos antes dos pais.
_DELETE_STATEMENTS = [
    (
        "notifications",
        """
        DELETE FROM notifications
        WHERE user_id IN (SELECT id FROM users WHERE telegram_chat_id <= :base)
        """,
    ),
    (
        "wishlist_listing_activity",
        """
        DELETE FROM wishlist_listing_activity
        WHERE wishlist_id IN (
            SELECT w.id FROM wishlists w
            JOIN users u ON u.id = w.user_id
            WHERE u.telegram_chat_id <= :base
        )
        """,
    ),
    (
        "wishlist_tracked_listings",
        """
        DELETE FROM wishlist_tracked_listings
        WHERE wishlist_id IN (
            SELECT w.id FROM wishlists w
            JOIN users u ON u.id = w.user_id
            WHERE u.telegram_chat_id <= :base
        )
        """,
    ),
    (
        "wishlist_tokens",
        """
        DELETE FROM wishlist_tokens
        WHERE wishlist_id IN (
            SELECT w.id FROM wishlists w
            JOIN users u ON u.id = w.user_id
            WHERE u.telegram_chat_id <= :base
        )
        """,
    ),
    (
        "fipe_lookup_requests",
        """
        DELETE FROM fipe_lookup_requests
        WHERE wishlist_id IN (
            SELECT w.id FROM wishlists w
            JOIN users u ON u.id = w.user_id
            WHERE u.telegram_chat_id <= :base
        )
        """,
    ),
    (
        "wishlist_filters",
        """
        DELETE FROM wishlist_filters
        WHERE wishlist_id IN (
            SELECT w.id FROM wishlists w
            JOIN users u ON u.id = w.user_id
            WHERE u.telegram_chat_id <= :base
        )
        """,
    ),
    (
        "wishlists",
        """
        DELETE FROM wishlists
        WHERE user_id IN (SELECT id FROM users WHERE telegram_chat_id <= :base)
        """,
    ),
    (
        "user_digest_preferences",
        "DELETE FROM user_digest_preferences WHERE user_id IN (SELECT id FROM users WHERE telegram_chat_id <= :base)",
    ),
    (
        "users",
        "DELETE FROM users WHERE telegram_chat_id <= :base",
    ),
]

_COUNT_STATEMENTS = {
    "notifications": "SELECT count(*) FROM notifications WHERE user_id IN (SELECT id FROM users WHERE telegram_chat_id <= :base)",
    "wishlist_listing_activity": """
        SELECT count(*) FROM wishlist_listing_activity
        WHERE wishlist_id IN (SELECT w.id FROM wishlists w JOIN users u ON u.id = w.user_id WHERE u.telegram_chat_id <= :base)
    """,
    "wishlist_tracked_listings": """
        SELECT count(*) FROM wishlist_tracked_listings
        WHERE wishlist_id IN (SELECT w.id FROM wishlists w JOIN users u ON u.id = w.user_id WHERE u.telegram_chat_id <= :base)
    """,
    "wishlist_tokens": """
        SELECT count(*) FROM wishlist_tokens
        WHERE wishlist_id IN (SELECT w.id FROM wishlists w JOIN users u ON u.id = w.user_id WHERE u.telegram_chat_id <= :base)
    """,
    "fipe_lookup_requests": """
        SELECT count(*) FROM fipe_lookup_requests
        WHERE wishlist_id IN (SELECT w.id FROM wishlists w JOIN users u ON u.id = w.user_id WHERE u.telegram_chat_id <= :base)
    """,
    "wishlist_filters": """
        SELECT count(*) FROM wishlist_filters
        WHERE wishlist_id IN (SELECT w.id FROM wishlists w JOIN users u ON u.id = w.user_id WHERE u.telegram_chat_id <= :base)
    """,
    "wishlists": "SELECT count(*) FROM wishlists WHERE user_id IN (SELECT id FROM users WHERE telegram_chat_id <= :base)",
    "user_digest_preferences": "SELECT count(*) FROM user_digest_preferences WHERE user_id IN (SELECT id FROM users WHERE telegram_chat_id <= :base)",
    "users": "SELECT count(*) FROM users WHERE telegram_chat_id <= :base",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    apply = bool(args.apply)
    params = {"base": LOAD_TEST_CHAT_ID_BASE}

    with SessionLocal() as db:
        mode = "apply" if apply else "dry-run"
        for name, count_sql in _COUNT_STATEMENTS.items():
            n = int(db.execute(text(count_sql), params).scalar_one())
            print(f"[{mode}] {name}: {n} candidato(s)")

        if not apply:
            print("\nNenhuma alteracao feita. Rode com --apply para remover.")
            return 0

        for name, delete_sql in _DELETE_STATEMENTS:
            if not settings.database_url.startswith("sqlite"):
                db.execute(text("SET LOCAL app.allow_core_data_delete = 'on'"))
            result = db.execute(text(delete_sql), params)
            print(f"[apply] {name}: {result.rowcount} removido(s)")
            db.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
