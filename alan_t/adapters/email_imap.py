"""Email adapter: stdlib IMAP/SMTP, no extra dependencies.

No new dependencies — imaplib/smtplib/email from the standard library, run in
worker threads. Reading is ALLOW-tier; sending is ASK-tier (the gate enforces
it — see config/permissions.yaml). Credentials live only in settings (.env).
"""

from __future__ import annotations

import asyncio
import email
import email.header
import imaplib
import logging
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr

log = logging.getLogger("alan_t.email")


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    return "".join(
        p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, enc in parts
    )


def _body_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return "(no text/plain part — HTML-only email)"
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace") if payload else ""


class EmailAdapter:
    def __init__(self, imap_host: str, smtp_host: str, address: str, password: str,
                 imap_port: int = 993, smtp_port: int = 587):
        self._imap_host, self._imap_port = imap_host, imap_port
        self._smtp_host, self._smtp_port = smtp_host, smtp_port
        self._address, self._password = address, password

    @property
    def configured(self) -> bool:
        return bool(self._imap_host and self._address and self._password)

    # ── read side (ALLOW) ──────────────────────────────────────────────

    def _list_sync(self, folder: str, limit: int, unread_only: bool) -> list[dict]:
        with imaplib.IMAP4_SSL(self._imap_host, self._imap_port) as imap:
            imap.login(self._address, self._password)
            imap.select(folder, readonly=True)
            _, data = imap.search(None, "UNSEEN" if unread_only else "ALL")
            uids = data[0].split()[-limit:]
            out = []
            for uid in reversed(uids):
                _, msg_data = imap.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                msg = email.message_from_bytes(msg_data[0][1])
                out.append({
                    "uid": uid.decode(),
                    "from": _decode(msg.get("From")),
                    "subject": _decode(msg.get("Subject")),
                    "date": msg.get("Date", ""),
                })
            return out

    def _read_sync(self, uid: str, folder: str) -> dict:
        with imaplib.IMAP4_SSL(self._imap_host, self._imap_port) as imap:
            imap.login(self._address, self._password)
            imap.select(folder, readonly=True)
            _, msg_data = imap.fetch(uid.encode(), "(BODY.PEEK[])")
            msg = email.message_from_bytes(msg_data[0][1])
            return {
                "uid": uid,
                "from": _decode(msg.get("From")),
                "to": _decode(msg.get("To")),
                "subject": _decode(msg.get("Subject")),
                "date": msg.get("Date", ""),
                "body": _body_text(msg)[:20000],
            }

    async def list_inbox(self, limit: int = 10, unread_only: bool = False,
                         folder: str = "INBOX") -> list[dict]:
        return await asyncio.to_thread(self._list_sync, folder, limit, unread_only)

    async def read_email(self, uid: str, folder: str = "INBOX") -> dict:
        return await asyncio.to_thread(self._read_sync, uid, folder)

    # ── send side (ASK — outward-facing, gated) ────────────────────────

    def _send_sync(self, to: str, subject: str, body: str) -> str:
        if not parseaddr(to)[1]:
            raise ValueError(f"not a valid recipient address: {to!r}")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self._address, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self._smtp_host, self._smtp_port) as smtp:
            smtp.starttls()
            smtp.login(self._address, self._password)
            smtp.send_message(msg)
        log.info("email sent to=%s subject=%r", to, subject[:60])
        return f"sent to {to}: {subject}"

    async def send_email(self, to: str, subject: str, body: str) -> str:
        return await asyncio.to_thread(self._send_sync, to, subject, body)
