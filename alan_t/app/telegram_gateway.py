"""Telegram gateway (Docs_COMPLEX/integrations/TELEGRAM.md) — a thin translation layer.

Separate process, same image. Consumes the internal HTTP API; holds no business
logic, gets no private endpoints. Long-polling → no inbound port.

The security line: exactly one TELEGRAM_ALLOWED_USER_ID. Updates from anyone else
are dropped and never answered (answering reveals the bot is alive).

Chats: every Telegram chat continues one Alan_T session. /chats lists the latest
10 sessions as a numbered picker; choosing one resumes it. /new starts fresh.
Voice notes are transcribed (Groq Whisper chain); photos go to the vision
pipeline (NVIDIA-primary, Google backup).
"""

from __future__ import annotations

import asyncio
import io
import logging
import os

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from alan_t.app.config import load_settings

log = logging.getLogger("alan_t.telegram")

settings = load_settings()
API_URL = os.environ.get("ALAN_API_URL", "http://127.0.0.1:8000")
HEADERS = {"Authorization": f"Bearer {settings.alan_api_token}"}
TG_LIMIT = 4096

dp = Dispatcher()
_sessions: dict[int, str] = {}  # chat_id → active session_id
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


def _allowed(event: Message | CallbackQuery) -> bool:
    global _dropped
    if event.from_user and event.from_user.id == settings.telegram_allowed_user_id:
        return True
    _dropped += 1
    log.warning("dropped update from unauthorized sender (total=%d)", _dropped)
    return False


def _pick_resume_session(sessions: list[dict]) -> str | None:
    """Most recent telegram-channel session, by activity. Single-user bot, so
    channel — not title — is the resume key: auto-titling renames sessions,
    and matching on a title placeholder silently forked chats after restarts."""
    for s in sessions:  # API returns newest-activity-first
        if s["channel"] == "telegram":
            return s["session_id"]
    return None


async def _session_for(client: httpx.AsyncClient, chat_id: int) -> str:
    """Active session for this chat — picked via /chats, else the newest
    telegram session (survives gateway restarts), else a fresh untitled one
    (the auto-titler names it after the first exchange)."""
    if chat_id not in _sessions:
        r = await client.get(f"{API_URL}/api/v1/chat/sessions", headers=HEADERS)
        r.raise_for_status()
        resumed = _pick_resume_session(r.json())
        if resumed:
            _sessions[chat_id] = resumed
        else:
            r = await client.post(f"{API_URL}/api/v1/chat/sessions", headers=HEADERS,
                                  json={"channel": "telegram"})
            r.raise_for_status()
            _sessions[chat_id] = r.json()["session_id"]
    return _sessions[chat_id]


def _approval_keyboard(approvals: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"✅ {a['tool']} #{a['id']}",
                                  callback_data=f"approve:{a['id']}"),
             InlineKeyboardButton(text="❌ deny", callback_data=f"deny:{a['id']}")]
            for a in approvals[:5]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _offer_approvals(client: httpx.AsyncClient, message: Message) -> None:
    """After a needs_approval turn: show the pending queue as tappable buttons."""
    r = await client.get(f"{API_URL}/api/v1/approvals", headers=HEADERS)
    if r.is_success and r.json():
        await message.answer("Pending approvals:", reply_markup=_approval_keyboard(r.json()))


async def _ask(client: httpx.AsyncClient, chat_id: int, content: str, reply,
               message: Message | None = None, speak: bool = False) -> None:
    """One chat turn against the API, honest on rate limits."""
    session_id = await _session_for(client, chat_id)
    r = await client.post(
        f"{API_URL}/api/v1/chat/sessions/{session_id}/messages",
        headers=HEADERS, json={"content": content},
    )
    if r.status_code == 503:
        await reply(f"Honest failure: {r.json().get('detail', 'rate-limited')}")
        return
    r.raise_for_status()
    data = r.json()
    for part in _chunk_reply(data["content"]):
        await reply(part)
    if speak and message is not None:
        # the user spoke first → reply with voice too (TELEGRAM.md); best-effort
        try:
            tr = await client.post(f"{API_URL}/api/v1/voice/speak", headers=HEADERS,
                                   json={"text": data["content"][:1500]})
            if tr.is_success:
                await message.answer_audio(
                    BufferedInputFile(tr.content, filename="alan_reply.wav"))
        except httpx.HTTPError:
            pass
    if data.get("status") == "needs_approval" and message is not None:
        await _offer_approvals(client, message)


# ── commands ──────────────────────────────────────────────────────────


WELCOME = """Hi — I'm Alan_T, your personal AI.

Just talk to me (text, voice notes, or photos). Commands:

Chats
/new — start a fresh chat
/list — all your chats (tap to switch)
/switch — quick picker, latest 10
/rename <name> — rename this chat
/delete — delete this chat
/project <name> — put this chat in a project (shared context)
/projects — list projects

Assistant
/goal <thing> — plan + execute a multi-step goal
/approvals — anything waiting for your OK
/digest — morning briefing now
/library — your notes, documents, images, uploads
/ingest — re-index your files
/status — health check

Send a file to add it to your library (and knowledge, if it's md/txt/pdf)."""


@dp.message(Command("start", "help"))
async def cmd_start(message: Message):
    if not _allowed(message):
        return
    await message.answer(WELCOME)


async def _chat_picker(message: Message, limit: int, note: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.get(f"{API_URL}/api/v1/chat/sessions", headers=HEADERS)
            r.raise_for_status()
        except httpx.HTTPError:
            await message.answer("backend unreachable")
            return
    sessions = r.json()[:limit]
    if not sessions:
        await message.answer("No chats yet — just send me a message to start one.")
        return
    active = _sessions.get(message.chat.id)
    lines, buttons = [], []
    for i, s in enumerate(sessions, 1):
        marker = " ← current" if s["session_id"] == active else ""
        title = s["title"] or "untitled"
        project = f" 〔{s['project']}〕" if s.get("project") else ""
        when = (s.get("last_message_at") or s["created_at"])[:16]
        lines.append(f"{i}. {title}{project} — {when}{marker}")
        buttons.append(InlineKeyboardButton(text=str(i), callback_data=f"pick:{s['session_id']}"))
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    await message.answer(note + "\n\n" + "\n".join(lines),
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.message(Command("list"))
async def cmd_list(message: Message):
    if not _allowed(message):
        return
    await _chat_picker(message, 20, "All your chats — tap a number to switch:")


@dp.message(Command("rename"))
async def cmd_rename(message: Message, command: CommandObject):
    if not _allowed(message):
        return
    if not command.args:
        await message.answer("Usage: /rename <new chat name>")
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            sid = await _session_for(client, message.chat.id)
            r = await client.patch(f"{API_URL}/api/v1/chat/sessions/{sid}",
                                   headers=HEADERS, json={"title": command.args.strip()[:80]})
            r.raise_for_status()
            await message.answer(f"Renamed this chat to “{command.args.strip()[:80]}”.")
        except httpx.HTTPError:
            await message.answer("backend unreachable")


@dp.message(Command("delete"))
async def cmd_delete(message: Message):
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=30) as client:
        sid = await _session_for(client, message.chat.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Yes, delete", callback_data=f"del:{sid}"),
        InlineKeyboardButton(text="Cancel", callback_data="del:cancel"),
    ]])
    await message.answer("Delete this chat and its history? This is permanent.",
                         reply_markup=keyboard)


@dp.callback_query(F.data.startswith("del:"))
async def on_delete(callback: CallbackQuery):
    if not _allowed(callback):
        return
    target = callback.data.removeprefix("del:")
    if target == "cancel":
        await callback.answer("kept")
        await callback.message.answer("Kept it.")
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.delete(f"{API_URL}/api/v1/chat/sessions/{target}", headers=HEADERS)
            r.raise_for_status()
            _sessions.pop(callback.message.chat.id, None)
            await callback.answer("deleted")
            await callback.message.answer("Deleted. Your next message starts a fresh chat.")
        except httpx.HTTPError:
            await callback.answer("backend unreachable", show_alert=True)


@dp.message(Command("projects"))
async def cmd_projects(message: Message):
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.get(f"{API_URL}/api/v1/projects", headers=HEADERS)
            r.raise_for_status()
            projects = r.json()
            if not projects:
                await message.answer("No projects yet. /project <name> puts this chat in one.")
                return
            await message.answer("Projects:\n" + "\n".join(
                f"- {p['name']} ({p['chats']} chats)"
                + (f" — {p['instructions'][:60]}" if p["instructions"] else "")
                for p in projects))
        except httpx.HTTPError:
            await message.answer("backend unreachable")


@dp.message(Command("project"))
async def cmd_project(message: Message, command: CommandObject):
    """/project <name> — assign current chat; /project none — ungroup."""
    if not _allowed(message):
        return
    if not command.args:
        await message.answer("Usage: /project <name>  (or `/project none` to ungroup). "
                             "/projects lists them.")
        return
    name = command.args.strip()
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            sid = await _session_for(client, message.chat.id)
            if name.lower() in ("none", "clear"):
                r = await client.patch(f"{API_URL}/api/v1/chat/sessions/{sid}",
                                       headers=HEADERS, json={"clear_project": True})
                r.raise_for_status()
                await message.answer("This chat is no longer in a project.")
                return
            r = await client.post(f"{API_URL}/api/v1/projects", headers=HEADERS,
                                  json={"name": name})
            r.raise_for_status()
            pid = r.json()["project_id"]
            r = await client.patch(f"{API_URL}/api/v1/chat/sessions/{sid}",
                                   headers=HEADERS, json={"project_id": pid})
            r.raise_for_status()
            await message.answer(f"This chat now lives in project “{name}”. Its instructions "
                                 "(if any) apply to every chat in it.")
        except httpx.HTTPError:
            await message.answer("backend unreachable")


@dp.message(Command("library"))
async def cmd_library(message: Message):
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.get(f"{API_URL}/api/v1/library", headers=HEADERS)
            r.raise_for_status()
            lib = r.json()
            lines = [f"Notes: {len(lib['notes'])}" ]
            lines += [f"  - {n['name']}" for n in lib["notes"][:5]]
            lines.append(f"Documents: {len(lib['documents'])}")
            lines += [f"  - {d['title']} (v{d['version']})" for d in lib["documents"][:5]]
            lines.append(f"Generated images: {len(lib['images'])}")
            lines.append(f"Uploads: {len(lib['uploads'])}")
            if "knowledge" in lib:
                lines.append(f"Knowledge chunks: {lib['knowledge'].get('chunks', 0)}")
            await message.answer("Your library:\n" + "\n".join(lines))
        except httpx.HTTPError:
            await message.answer("backend unreachable")


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


@dp.message(Command("new"))
async def cmd_new(message: Message):
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(f"{API_URL}/api/v1/chat/sessions", headers=HEADERS,
                                  json={"channel": "telegram"})
            r.raise_for_status()
            _sessions[message.chat.id] = r.json()["session_id"]
            await message.answer("Started a fresh chat. (/chats to go back to an older one)")
        except httpx.HTTPError:
            await message.answer("backend unreachable")


@dp.message(Command("chats", "switch"))
async def cmd_chats(message: Message):
    """Latest 10 sessions as a numbered picker — choose one to continue it."""
    if not _allowed(message):
        return
    await _chat_picker(message, 10, "Your latest chats — tap a number to continue that one:")


@dp.callback_query(F.data.startswith("pick:"))
async def on_pick(callback: CallbackQuery):
    if not _allowed(callback):
        return
    session_id = callback.data.removeprefix("pick:")
    _sessions[callback.message.chat.id] = session_id
    async with httpx.AsyncClient(timeout=30) as client:
        last = ""
        try:
            r = await client.get(f"{API_URL}/api/v1/chat/sessions/{session_id}", headers=HEADERS)
            turns = [t for t in r.json() if t["role"] == "assistant"]
            if turns:
                snippet = turns[-1]["content"]
                last = f"\n\nLast reply there:\n{snippet[:300]}{'…' if len(snippet) > 300 else ''}"
        except httpx.HTTPError:
            pass
    await callback.answer("resumed")
    await callback.message.answer(f"Continuing that chat — just keep typing.{last}")


@dp.message(Command("goal"))
async def cmd_goal(message: Message, command: CommandObject):
    """Jarvis mode: /goal <what you want done> → plan → execute → report."""
    if not _allowed(message):
        return
    if not command.args:
        await message.answer("Usage: /goal <what you want done>")
        return
    await message.answer("On it — planning and executing…")
    async with httpx.AsyncClient(timeout=300) as client:
        try:
            r = await client.post(f"{API_URL}/api/v1/tasks", headers=HEADERS,
                                  json={"goal": command.args})
            if r.status_code == 422:
                await message.answer(f"Couldn't build a valid plan: {r.json().get('detail')}")
                return
            r.raise_for_status()
            record = r.json()
            lines = [f"Task {record['status']}: {command.args[:80]}"]
            lines += [f"  {s['step']}. [{s['agent']}] {s['status']}: {s['response'][:150]}"
                      for s in record["steps"]]
            if record.get("reflection"):
                lines.append(f"Verdict: {record['reflection'].get('verdict', '?')}")
            for part in _chunk_reply("\n".join(lines)):
                await message.answer(part)
            if record["status"] == "waiting_approval":
                await _offer_approvals(client, message)
        except httpx.HTTPError:
            await message.answer("backend unreachable")


@dp.message(Command("approvals"))
async def cmd_approvals(message: Message):
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.get(f"{API_URL}/api/v1/approvals", headers=HEADERS)
            r.raise_for_status()
            pending = r.json()
            if not pending:
                await message.answer("Nothing waiting for approval.")
                return
            text = "\n".join(f"#{a['id']}: {a['preview'][:150]}" for a in pending)
            await message.answer(f"Pending approvals:\n{text}",
                                 reply_markup=_approval_keyboard(pending))
        except httpx.HTTPError:
            await message.answer("backend unreachable")


@dp.callback_query(F.data.startswith(("approve:", "deny:")))
async def on_approval(callback: CallbackQuery):
    if not _allowed(callback):
        return
    action, _, approval_id = callback.data.partition(":")
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            r = await client.post(f"{API_URL}/api/v1/approvals/{approval_id}",
                                  headers=HEADERS, json={"approve": action == "approve"})
            r.raise_for_status()
            data = r.json()
            await callback.answer(data["status"])
            outcome = data.get("result") or data["status"]
            await callback.message.answer(f"[{data['tool']} #{data['id']}] {outcome[:1000]}")
        except httpx.HTTPError:
            await callback.answer("backend unreachable", show_alert=True)


@dp.message(Command("digest"))
async def cmd_digest(message: Message):
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            r = await client.post(f"{API_URL}/api/v1/automations/morning_digest/run",
                                  headers=HEADERS)
            await message.answer("Digest sent." if r.is_success
                                 else f"Digest failed: {r.json().get('detail', r.status_code)}")
        except httpx.HTTPError:
            await message.answer("backend unreachable")


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


# ── media ─────────────────────────────────────────────────────────────


async def _download(bot: Bot, file_id: str) -> bytes:
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    return buf.getvalue()


@dp.message(F.voice | F.audio)
async def on_voice(message: Message):
    """Voice note → hosted STT (Groq Whisper chain) → normal chat turn."""
    if not _allowed(message):
        return
    media = message.voice or message.audio
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            audio = await _download(message.bot, media.file_id)
            r = await client.post(
                f"{API_URL}/api/v1/voice/transcribe", headers=HEADERS,
                files={"audio": ("note.ogg", audio, "audio/ogg")},
            )
            if r.status_code == 503:
                await message.answer(f"Honest failure: {r.json().get('detail', 'rate-limited')}")
                return
            r.raise_for_status()
            transcript = r.json()["text"].strip()
            if not transcript:
                await message.answer("I couldn't hear anything in that voice note.")
                return
            await message.answer(f"🎙️ heard: “{transcript}”")
            await _ask(client, message.chat.id, transcript, message.answer,
                       message=message, speak=True)
        except httpx.HTTPError:
            await message.answer("backend unreachable")


@dp.message(F.photo)
async def on_photo(message: Message):
    """Photo → vision pipeline (NVIDIA-primary, Google backup); caption = question."""
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            image = await _download(message.bot, message.photo[-1].file_id)
            r = await client.post(
                f"{API_URL}/api/v1/vision/analyze", headers=HEADERS,
                files={"image": ("photo.jpg", image, "image/jpeg")},
                data={"question": message.caption or "Describe this image in detail."},
            )
            if r.status_code == 503:
                await message.answer(f"Honest failure: {r.json().get('detail', 'rate-limited')}")
                return
            r.raise_for_status()
            for part in _chunk_reply(r.json()["content"]):
                await message.answer(part)
        except httpx.HTTPError:
            await message.answer("backend unreachable")


@dp.message(F.document)
async def on_document(message: Message):
    """File → library upload; md/txt/pdf also enter the knowledge base."""
    if not _allowed(message):
        return
    doc = message.document
    async with httpx.AsyncClient(timeout=180) as client:
        try:
            blob = await _download(message.bot, doc.file_id)
            r = await client.post(
                f"{API_URL}/api/v1/library/upload", headers=HEADERS,
                files={"file": (doc.file_name or "upload.bin", blob)},
            )
            r.raise_for_status()
            data = r.json()
            note = " Indexing it into your knowledge now." if data["ingest_started"] else ""
            await message.answer(f"Saved to your library as {data['saved']}.{note}")
        except httpx.HTTPError:
            await message.answer("backend unreachable")


@dp.message(F.text)
async def on_text(message: Message):
    if not _allowed(message):
        return
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            await _ask(client, message.chat.id, message.text, message.answer, message=message)
        except httpx.HTTPError:
            await message.answer("backend unreachable")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    if not settings.telegram_allowed_user_id:
        raise SystemExit("TELEGRAM_ALLOWED_USER_ID is not set — refusing to run an open bot")
    bot = Bot(token=settings.telegram_bot_token)
    await bot.set_my_commands([
        BotCommand(command="new", description="Start a fresh chat"),
        BotCommand(command="list", description="All chats — tap to switch"),
        BotCommand(command="switch", description="Quick chat picker"),
        BotCommand(command="goal", description="Plan + execute a multi-step goal"),
        BotCommand(command="approvals", description="Approve/deny pending actions"),
        BotCommand(command="project", description="Put this chat in a project"),
        BotCommand(command="rename", description="Rename this chat"),
        BotCommand(command="delete", description="Delete this chat"),
        BotCommand(command="library", description="Notes, documents, images, uploads"),
        BotCommand(command="digest", description="Morning briefing now"),
        BotCommand(command="status", description="Backend health"),
        BotCommand(command="help", description="All commands"),
    ])
    log.info("telegram gateway: long-polling as single-user bot")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
