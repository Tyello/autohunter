#!/usr/bin/env python3
"""Gerencia a sessao logada do Mercado Livre usada pela source `mercadolivre`.

  status                      resumo do arquivo e da saude registrada (AppKV)
  install <storage_state.json> valida e instala (com backup) o storage_state
  capture --cdp-url URL       exporta a sessao de um Chrome aberto com --remote-debugging-port

Ver docs/OPERATIONS_RUNBOOK.md ("Sessao do Mercado Livre"). Nunca imprime valores de cookie.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import ml_session_service as svc
from app.services.storage_state_cookies import storage_state_path


def _target(proxy: str | None) -> Path:
    return storage_state_path(source=svc.SOURCE, proxy_server=proxy)


def cmd_status(args) -> int:
    info = svc.session_info(args.proxy)
    print(json.dumps({"file": str(_target(args.proxy)), "session": info}, indent=2, default=str))
    try:
        from app.db.session import session_scope
        from app.services.app_kv_service import get_kv

        with session_scope() as db:
            print(json.dumps({"health": get_kv(db, svc.HEALTH_KV_KEY)}, indent=2, default=str))
    except Exception as exc:  # DB indisponivel nao impede ver o arquivo
        print(f"health indisponivel: {type(exc).__name__}")
    return 0 if info["logged_in"] else 1


def _validate(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cookies = [c for c in (data.get("cookies") or []) if "mercadoli" in str(c.get("domain", ""))]
    names = {c.get("name") for c in cookies if c.get("value")}
    missing = [n for n in svc.AUTH_COOKIE_NAMES if n not in names]
    if missing:
        raise SystemExit(f"storage_state sem login do ML (faltam cookies: {', '.join(missing)})")
    return cookies


def cmd_install(args) -> int:
    src = Path(args.file)
    _validate(src)
    dst = _target(args.proxy)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        backup = dst.with_name(f"{dst.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(dst, backup)
        print(f"backup: {backup}")
    shutil.copy2(src, dst)
    dst.chmod(0o600)
    print(f"instalado: {dst}")
    print(json.dumps(svc.session_info(args.proxy), indent=2, default=str))
    return 0


def cmd_capture(args) -> int:
    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp_url)
        browser.contexts[0].storage_state(path=str(out))
    _validate(out)
    out.chmod(0o600)
    print(f"sessao exportada para {out} (use 'install' para ativar)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", default=None, help="proxy_server da source (default: sem proxy)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p_install = sub.add_parser("install")
    p_install.add_argument("file")
    p_install.set_defaults(fn=cmd_install)
    p_cap = sub.add_parser("capture")
    p_cap.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    p_cap.add_argument("--out", default="storage_mercadolivre.json")
    p_cap.set_defaults(fn=cmd_capture)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
