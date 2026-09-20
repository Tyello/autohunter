"""
Load-test seed: cria usuarios sinteticos com wishlist ativa para o teste de
carga pre-beta descrito em docs/OPERATIONS_RUNBOOK.md secao 14.

Usuarios sinteticos usam telegram_chat_id numa faixa negativa reservada
(nunca colide com chat_id real do Telegram, que e sempre positivo), o que
permite identificar e remover esses dados com seguranca via
scripts/load_test_teardown.py.

Idempotente: rodar de novo com o mesmo --users s0 cria o que faltar.

Uso:
    python scripts/load_test_seed.py --users 50
"""
from __future__ import annotations

import argparse
import uuid

from app.db.session import SessionLocal
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.wishlist_tokens_service import rebuild_tokens_for_wishlist

# Faixa reservada para chat_id sintetico: chat_id real do Telegram e sempre > 0.
LOAD_TEST_CHAT_ID_BASE = -900_000_000_000
LOAD_TEST_USERNAME_PREFIX = "loadtest_"

# Buscas realistas de entusiasta automotivo (mesmo estilo usado em
# docs/LAUNCH_PLAN.md e scripts/bench_matching.py), repetidas em ciclo se
# --users pedir mais do que itens na lista. Mantidas unicas ate 50 itens para
# que um teste de carga com --users 50 exercite 50 padroes de busca distintos
# em vez de repetir um conjunto menor.
_QUERIES = [
    "civic si manual",
    "golf gti mk7",
    "jetta gli",
    "subaru wrx",
    "opala comodoro",
    "audi a5 2.0",
    "bmw 320i sport",
    "corolla xei manual",
    "hb20 turbo",
    "onix plus turbo",
    "fiesta se manual",
    "gol gti",
    "polo gts",
    "cruze sport6 turbo",
    "hb20s premium",
    "creta ultimate",
    "compass longitude",
    "renegade trailhawk",
    "tracker premier",
    "kicks sv",
    "duster oroch",
    "toro freedom",
    "hilux srx",
    "s10 high country",
    "ranger limited",
    "amarok highline",
    "corolla cross xre",
    "kicks advance",
    "civic touring",
    "sentra advance",
    "versa exclusive",
    "logan iconic",
    "sandero rs",
    "argo trekking",
    "mobi trekking",
    "kwid outsider",
    "kicks sr",
    "yaris xls",
    "city touring",
    "hr-v touring",
    "wr-v exl",
    "spin activ7",
    "trailblazer premier",
    "pajero sport hpe",
    "outlander gt",
    "tiguan allspace",
    "t-cross highline",
    "nivus highline",
    "captur intense",
    "2008 tech",
    "c4 cactus feel",
]


def load_test_chat_id(index: int) -> int:
    return LOAD_TEST_CHAT_ID_BASE - index


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--users", type=int, default=50)
    args = p.parse_args()
    n = max(1, int(args.users))

    created_users = 0
    created_wishlists = 0
    skipped = 0

    with SessionLocal() as db:
        for i in range(n):
            chat_id = load_test_chat_id(i)
            user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
            if user is None:
                user = User(
                    id=uuid.uuid4(),
                    telegram_chat_id=chat_id,
                    username=f"{LOAD_TEST_USERNAME_PREFIX}{i}",
                    is_active=True,
                    plan="free",
                )
                db.add(user)
                db.flush()
                created_users += 1
            else:
                skipped += 1

            existing_wishlist = (
                db.query(Wishlist)
                .filter(Wishlist.user_id == user.id, Wishlist.deleted_at.is_(None))
                .first()
            )
            if existing_wishlist is None:
                query = _QUERIES[i % len(_QUERIES)]
                wishlist = Wishlist(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    query=query,
                    is_active=True,
                )
                db.add(wishlist)
                db.flush()
                rebuild_tokens_for_wishlist(db, wishlist)
                created_wishlists += 1

            db.commit()

        print(
            f"[load_test_seed] users_created={created_users} "
            f"users_already_existed={skipped} wishlists_created={created_wishlists} "
            f"chat_id_range=[{load_test_chat_id(n - 1)}, {load_test_chat_id(0)}]"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
