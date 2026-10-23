import pytest

from app.core.settings import settings
from app.services import system_logs_service


class _FakeDb:
    def add(self, row):
        pass


@pytest.mark.parametrize(
    "min_level, level, printed",
    [
        ("warning", "info", False),
        ("warning", "debug", False),
        ("warning", "warn", True),
        ("warning", "WARNING", True),
        ("warning", "error", True),
        ("error", "warn", False),
        ("debug", "info", True),
        ("bogus", "info", True),
    ],
)
def test_stdout_mirror_respects_min_level(monkeypatch, capsys, min_level, level, printed):
    monkeypatch.setattr(settings, "log_stdout", True)
    monkeypatch.setattr(settings, "log_stdout_min_level", min_level)

    system_logs_service.log(_FakeDb(), level, "comp", "msg")

    assert ("comp msg" in capsys.readouterr().out) is printed


def test_stdout_mirror_off_when_disabled(monkeypatch, capsys):
    monkeypatch.setattr(settings, "log_stdout", False)
    system_logs_service.log(_FakeDb(), "error", "comp", "msg")
    assert capsys.readouterr().out == ""
