"""Telegram gateway (Docs/integrations/TELEGRAM.md) — a thin translation layer.

Separate process, same image. Consumes the internal HTTP API; holds no business
logic, gets no private endpoints. Long-polling → no inbound port.

The security line: exactly one TELEGRAM_ALLOWED_USER_ID. Updates from anyone else
are dropped and never answered (answering reveals the bot is alive).
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from alan_t.app.config import load_settings

log = logging.getLogger("alan_t.telegram")

settings = load_settings()
API_URL = os.environ.get("ALAN_API_URL", "http://127.0.0.1:8000")
HEADERS = {"Authorization": f"Bearer {settings.alan_api_token}"}
TG_LIMIT = 4096

dp = Dispatcher()
_sessions: dict[int, str] = {}  # chat_id → session_id
_dropped = 0


def _chunk_reply(text: str) -> list[str]:
    """Chunk long answers at 4096 chars on paragraph boundaries."""
    if len(text) <= TG_LIMIT:
        return [text]
    parts, cur = [], ""
    for para in text.split("\n\n"):
        candidate = f"{cur}\n\n{para}" if cur else para
        if len(candidate) > TG_LIMIT:
            if cur:
                parts.append(cur)
            while len(para) > TG_LIMIT:  # single paragraph longer than the limit
                parts.append(para[:TG_LIMIT])
                para = para[TG_LIMIT:]
            cur = para
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts


def _allowed(message: Message) -> bool:
    global _dropped
    if message.from_user and message.from_user.id == settings.telegram_allowed_user_id:
        return True
    _dropped += 1
    log.warning("dropped update from unauthorized sender (total=%d)", _dropped)
    return False


async def _session_for(client: httpx.AsyncClient, chat_id: int) -> str:
    if chat_id not in _sessions:
        # reuse the existing telegram session for this chat if one exists
        r = await client.get(f"{API_URL}/api/v1/chat/sessions", headers=HEADERS)
        r.raise_for_status()
        for s in r.json():
            if s["channel"] == "telegram" and s["title"] == f"telegram:{chat_id}":
                _sessions[chat_id] = s["session_id"]
                break
        else:
            r = await client.post(
                f"{API_URL}/api/v1/chat/sessions", headers=HEADERS,
                json={"channel": "telegram", "title": f"telegram:{chat_id}"},
            )
            r.raise_for_status()
            _sessions[chat_id] = r.json()["session_id"]
    return _sessions[chat_id]


@dp.message(Command("status"))
async def cmd_status(message: Message):
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.get(f"{API_URL}/api/v1/health/deps", headers=HEADERS)
            deps = "\n".join(f"{k}: {v}" for k, v in r.json().items())
            await message.answer(f"Alan_T status:\n{deps}")
        except httpx.HTTPError:
            await message.answer("backend unreachable")


@dp.message(F.voice | F.audio)
async def on_voice(message: Message):
    if not _allowed(message):
        return
    await message.answer("Voice notes aren't supported yet — coming with the voice milestone.")


@dp.message(F.document)
async def on_document(message: Message):
    if not _allowed(message):
        return
    await message.answer(
        "File received, but Telegram file ingestion isn't wired yet — "
        "put it in a configured mount (config/vfs.yaml) and send /ingest, "
        "or use POST /api/v1/ingest."
    )


@dp.message(Command("ingest"))
async def cmd_ingest(message: Message):
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(f"{API_URL}/api/v1/ingest", headers=HEADERS)
            r.raise_for_status()
            await message.answer("Ingestion started. /status for health, or check /ingest/status.")
        except httpx.HTTPError as e:
            await message.answer(f"couldn't start ingestion: {e}")


@dp.message(F.text)
async def on_text(message: Message):
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            session_id = await _session_for(client, message.chat.id)
            r = await client.post(
                f"{API_URL}/api/v1/chat/sessions/{session_id}/messages",
                headers=HEADERS, json={"content": message.text},
            )
            if r.status_code == 503:
                detail = r.json().get("detail", "rate-limited")
                await message.answer(f"Honest failure: {detail}")
                return
            r.raise_for_status()
            for part in _chunk_reply(r.json()["content"]):
                await message.answer(part)
        except httpx.HTTPError:
            await message.answer("backend unreachable")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    if not settings.telegram_allowed_user_id:
        raise SystemExit("TELEGRAM_ALLOWED_USER_ID is not set — refusing to run an open bot")
    bot = Bot(token=settings.telegram_bot_token)
    log.info("telegram gateway: long-polling as single-user bot")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
