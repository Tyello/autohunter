from __future__ import annotations

import re
from pathlib import Path


def test_callback_prefixes_have_registered_patterns():
    bot_files = [Path("app/bot/handlers_core.py"), Path("app/bot/handlers_wishlist_ui.py"), Path("app/bot/renderers.py")]
    callbacks: set[str] = set()
    for file in bot_files:
        text = file.read_text(encoding="utf-8")
        callbacks.update(re.findall(r'"((?:MENU|WL|FILTER|CWL|CWLF|W|TRACK|UPGRADE):[^"]+)"', text))

    prefixes = {cb.split(":", 1)[0] for cb in callbacks}
    assert {"MENU", "WL", "FILTER", "CWL", "CWLF", "W", "TRACK", "UPGRADE"}.issubset(prefixes)

    run_text = Path("app/bot/run.py").read_text(encoding="utf-8")
    for required in [
        r"^MENU:[A-Z_]+$",
        r"^UPGRADE:(MONTHLY|ANNUAL)$",
        r"^W:ADD:(SAVE|CANCEL)$",
        r"^W:CLEAR:(YES|NO)$",
        r"^(TRACK:ADD:[^:]+|TRACK:ADDWL:[^:]+:[^:]+|TRACK:ADDT:[^:]+|TRACK:CHOOSE:[^:]+)$",
    ]:
        assert required in run_text
    assert r"^WL:FILTERS:\d+$" in Path("app/bot/handlers_core.py").read_text(encoding="utf-8")
