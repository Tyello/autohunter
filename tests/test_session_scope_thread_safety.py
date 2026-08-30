"""Tests for session_scope() context manager and ThreadSafeSession thread safety."""

import threading
import uuid

import pytest
from sqlalchemy import text

from app.db.session import SessionLocal, session_scope, ThreadSafeSession
from app.models.system_log import SystemLog


def test_session_scope_commits_on_success():
    """session_scope() commits and persists changes on successful exit."""
    log_id = uuid.uuid4()

    with session_scope() as db:
        log = SystemLog(
            id=log_id,
            level="info",
            component="test_component",
            message="test message"
        )
        db.add(log)

    # Open new session and verify the log was persisted
    with session_scope() as db:
        found_log = db.query(SystemLog).filter_by(id=log_id).first()
        assert found_log is not None
        assert found_log.message == "test message"


def test_session_scope_rolls_back_and_reraises_on_exception():
    """session_scope() rolls back changes and re-raises exceptions."""
    log_id = uuid.uuid4()

    with pytest.raises(ValueError, match="test error"):
        with session_scope() as db:
            log = SystemLog(
                id=log_id,
                level="info",
                component="test_component",
                message="test message"
            )
            db.add(log)
            raise ValueError("test error")

    # Verify the log was NOT persisted
    with session_scope() as db:
        found_log = db.query(SystemLog).filter_by(id=log_id).first()
        assert found_log is None


def test_session_used_from_creating_thread_works():
    """ThreadSafeSession allows use from the thread that created it."""
    db = SessionLocal()
    try:
        # Should not raise
        result = db.execute(text("SELECT 1"))
        assert result is not None

        # Also test query method
        db.query(SystemLog).all()

        # Also test add/commit methods
        log = SystemLog(
            id=uuid.uuid4(),
            level="info",
            component="test",
            message="test"
        )
        db.add(log)
        db.commit()
    finally:
        db.close()


def test_session_used_from_other_thread_raises():
    """ThreadSafeSession raises RuntimeError when used from a different thread."""
    db = SessionLocal()
    result_box = {"execute_error": None, "commit_error": None}

    def worker():
        # Try execute() in different thread
        try:
            db.execute(text("SELECT 1"))
        except RuntimeError as e:
            result_box["execute_error"] = str(e)

        # Try commit() in different thread
        try:
            db.commit()
        except RuntimeError as e:
            result_box["commit_error"] = str(e)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    # Verify that RuntimeError was raised in the worker thread for execute
    assert result_box["execute_error"] is not None
    assert "Acesso de thread cruzada" in result_box["execute_error"]
    assert "thread" in result_box["execute_error"].lower()

    # Verify that RuntimeError was raised in the worker thread for commit
    assert result_box["commit_error"] is not None
    assert "Acesso de thread cruzada" in result_box["commit_error"]

    db.close()


def test_session_scope_session_is_thread_safe_instance():
    """session_scope() yields a ThreadSafeSession instance."""
    with session_scope() as db:
        assert isinstance(db, ThreadSafeSession)
        assert type(db).__name__ == "ThreadSafeSession"
