from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path

import httpx
import websockets
from playwright.async_api import async_playwright

from app.integrations.facebook.constants import MARKETPLACE_URL, STATUS_ACTIVE
from app.integrations.facebook.validator import classify_marketplace_state
from fb_agent import __version__


def _agent_id() -> str:
    p = Path.home() / ".autohunter" / "agent_id"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        return p.read_text().strip()
    value = uuid.uuid4().hex[:12]
    p.write_text(value)
    return value


async def _validate_local(page):
    await page.goto(MARKETPLACE_URL, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(1500)
    html = await page.content()
    return classify_marketplace_state(final_url=page.url, html=html)


async def run(code: str, server: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        bootstrap = await client.get(f"{server.rstrip('/')}/auth/facebook/agent/bootstrap", params={"code": code})
        bootstrap.raise_for_status()
        data = bootstrap.json()

    user_id = data["user_id"]
    ws_url = data["ws_url"]
    if ws_url.startswith("/"):
        ws_url = server.rstrip("/").replace("http://", "ws://").replace("https://", "wss://") + ws_url

    user_data_dir = Path.home() / ".autohunter" / "fb" / user_id
    user_data_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(user_data_dir=str(user_data_dir), headless=False)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(MARKETPLACE_URL, wait_until="domcontentloaded", timeout=45000)
        input("Faça login no Facebook no navegador aberto e pressione Enter aqui...")
        first = await _validate_local(page)
        print(f"Validation: {first.status} ({first.error_kind})")

        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({"token": data["token"], "agent_id": _agent_id(), "agent_version": __version__}))

            async def heartbeat():
                while True:
                    await asyncio.sleep(30)
                    await ws.send(json.dumps({"type": "pong"}))

            hb = asyncio.create_task(heartbeat())
            try:
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    if msg.get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                        continue
                    if msg.get("type") == "validate_session":
                        result = await _validate_local(page)
                        await ws.send(
                            json.dumps(
                                {
                                    "task_id": msg.get("task_id"),
                                    "ok": result.status == STATUS_ACTIVE,
                                    "status": result.status,
                                    "reason": result.error_message,
                                    "error_kind": result.error_kind,
                                }
                            )
                        )
            finally:
                hb.cancel()
                await context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoHunter Facebook Agent")
    parser.add_argument("--code", required=True)
    parser.add_argument("--server", required=True)
    args = parser.parse_args()
    asyncio.run(run(code=args.code, server=args.server))
