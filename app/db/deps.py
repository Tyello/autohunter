from sqlalchemy.orm import Session
from app.db.session import SessionLocalHTTP

def get_db() -> Session:
    db = SessionLocalHTTP()
    try:
        yield db
    finally:
        db.close()
