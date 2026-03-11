from types import SimpleNamespace

from app.scheduler.jobs_send import send_queued_notifications


class _FakeDB:
    def __init__(self):
        self.commit_calls = 0

    def commit(self):
        self.commit_calls += 1


def _notification(i: int):
    user = SimpleNamespace(id=i, telegram_chat_id=1000 + i)
    listing = SimpleNamespace(external_id=f"L{i}")
    return SimpleNamespace(id=i, user_id=i, user=user, car_listing=listing)


def test_sender_micro_batch_commits_in_chunks(monkeypatch):
    db = _FakeDB()
    queued = [_notification(1), _notification(2), _notification(3)]

    monkeypatch.setattr("app.scheduler.jobs_send.claim_queued_notifications", lambda *_args, **_kwargs: queued)
    monkeypatch.setattr("app.scheduler.jobs_send.can_send_more_today", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("app.scheduler.jobs_send.mark_notification_sent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.scheduler.jobs_send.log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.scheduler.jobs_send.settings", SimpleNamespace(notification_sender_commit_batch_size=2))

    sent = send_queued_notifications(db, component="sender-test", sender_fn=lambda *_args, **_kwargs: None)

    assert sent == 3
    # 2 commits for item state flushes (2 + 1), plus final log commit
    assert db.commit_calls == 3
