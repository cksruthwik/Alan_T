"""Outbound notifications: Telegram (direct Bot API) and ntfy push.

The scheduler and Automation agent live in the API process; the Telegram
gateway is a separate long-polling process — so proactive pushes go straight
to the Bot API here rather than through the gateway.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger("alan_t.notify")


class Notifier:
    def __init__(self, telegram_token: str = "", telegram_chat_id: int = 0,
                 ntfy_topic: str = ""):
        self._tg_token = telegram_token
        self._tg_chat = telegram_chat_id
        self._ntfy_topic = ntfy_topic

    @property
    def configured(self) -> bool:
        return bool((self._tg_token and self._tg_chat) or self._ntfy_topic)

    async def send(self, text: str, title: str = "Alan_T") -> str:
        delivered = []
        async with httpx.AsyncClient(timeout=15) as client:
            if self._tg_token and self._tg_chat:
                r = await client.post(
                    f"https://api.telegram.org/bot{self._tg_token}/sendMessage",
                    json={"chat_id": self._tg_chat, "text": text[:4096]})
                if r.is_success:
                    delivered.append("telegram")
                else:
                    log.warning("telegram notify failed: %s", r.text[:200])
            if self._ntfy_topic:
                r = await client.post(f"https://ntfy.sh/{self._ntfy_topic}",
                                      content=text.encode(), headers={"Title": title})
                if r.is_success:
                    delivered.append("ntfy")
        if not delivered:
            raise RuntimeError("no notification channel configured or all sends failed")
        return f"notified via {', '.join(delivered)}"
