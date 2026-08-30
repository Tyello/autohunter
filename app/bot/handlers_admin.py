"""Backward-compat shim.

The admin command dispatcher and its handlers now live in the
``app.bot.admin`` package (see ``app.bot.admin.router`` for the
``cmd_admin`` dispatch function). This module re-exports the names that
external callers and tests still import from ``app.bot.handlers_admin``
by their historical dotted path.
"""

from __future__ import annotations

from app.bot.admin import is_admin
from app.core.settings import settings

from app.bot.admin.router import cmd_admin

from app.bot.admin.sources import (
    _render_run_summary_lines,
    _render_webmotors_blocked_diag_lines,
)
from app.bot.admin.users import (
    _admin_users,
)

__all__ = [
    "is_admin",
    "settings",
    "cmd_admin",
    "_render_run_summary_lines",
    "_render_webmotors_blocked_diag_lines",
    "_admin_users",
]
