import uuid
from sqlalchemy.orm import Session

from app.models.user import User


def get_or_create_user_by_chat(db: Session, chat_id: int, username: str | None):
    u = db.query(User).filter(User.telegram_chat_id == chat_id).first()
    if u:
        return u

    u = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=username, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u
