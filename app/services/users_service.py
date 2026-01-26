import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User


def get_or_create_user_by_chat(db: Session, chat_id: int, username: str | None):
    # Se o Session veio "sujo" (ex.: transação abortada por erro anterior), limpa.
    # Isso evita: InFailedSqlTransaction.
    try:
        db.rollback()
    except Exception:
        pass

    u = db.query(User).filter(User.telegram_chat_id == chat_id).first()
    if u:
        # Atualiza username se mudou (best-effort)
        if username and u.username != username:
            u.username = username
            try:
                db.commit()
            except Exception:
                db.rollback()
        return u

    try:
        u = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=username, is_active=True)
        db.add(u)
        db.flush()

        acc = Account(type="personal", name=None, is_active=True)
        db.add(acc)
        db.flush()

        u.account_id = acc.id

        db.add(AccountMember(account_id=acc.id, user_id=u.id, role="owner"))

        free = db.query(Plan).filter(Plan.code == "free").first()
        if not free:
            raise RuntimeError("Plan free not found. Run migrations/seed.")

        db.add(Subscription(account_id=acc.id, plan_id=free.id, status="active", source="manual"))

        db.commit()
        db.refresh(u)
        return u

    except IntegrityError:
        # Corrige condição de corrida (2 updates do Telegram chegando juntos)
        db.rollback()
        u = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if u:
            return u
        raise
    except Exception:
        db.rollback()
        raise
