from __future__ import annotations

import asyncio

from telegram import BotCommandScopeChat, BotCommandScopeDefault

from app.bot import commands


class _FakeBot:
    def __init__(self):
        self.calls = []

    async def set_my_commands(self, cmds, scope):
        self.calls.append((cmds, scope))


def test_public_commands_are_slim_and_exclude_admin():
    names = [c.command for c in commands.PUBLIC_COMMANDS]
    assert names == ["start", "menu", "help", "cancelar"]
    assert "debug" not in names
    assert "admin" not in names
    assert "setplan" not in names
    assert "setlimit" not in names


def test_admin_commands_exist_and_are_separate():
    names = {c.command for c in commands.ADMIN_COMMANDS}
    assert {"admin", "debug", "setplan", "setlimit"}.issubset(names)


def test_admin_scoped_commands_include_public_plus_admin():
    names = [c.command for c in commands.ADMIN_SCOPED_COMMANDS]
    for cmd in ("start", "menu", "help", "cancelar", "admin", "debug", "setplan", "setlimit"):
        assert cmd in names


def test_advanced_user_commands_remain_out_of_public_menu():
    advanced_names = {c.command for c in commands.ADVANCED_USER_COMMANDS}
    public_names = {c.command for c in commands.PUBLIC_COMMANDS}
    assert "buscar" in advanced_names
    assert "wishlist" in advanced_names
    assert "wishlist_track_list" in advanced_names
    assert public_names.isdisjoint({"buscar", "wishlist", "wishlist_track_list"})


def test_setup_bot_commands_registers_default_and_admin_scopes(monkeypatch):
    fake = _FakeBot()
    monkeypatch.setattr(commands, "_parse_admin_chat_ids", lambda: {101, 202})

    asyncio.run(commands.setup_bot_commands(fake))

    assert isinstance(fake.calls[0][1], BotCommandScopeDefault)
    assert [c.command for c in fake.calls[0][0]] == [c.command for c in commands.PUBLIC_COMMANDS]

    admin_scopes = [scope for _cmds, scope in fake.calls[1:]]
    admin_calls = [cmds for cmds, _scope in fake.calls[1:]]
    assert len(admin_scopes) == 2
    assert all(isinstance(scope, BotCommandScopeChat) for scope in admin_scopes)
    assert sorted(scope.chat_id for scope in admin_scopes) == [101, 202]
    assert all([c.command for c in call] == [c.command for c in commands.ADMIN_SCOPED_COMMANDS] for call in admin_calls)
