"""Google Calendar adapter (Docs_COMPLEX/integrations/GOOGLE_CALENDAR.md).

Plain httpx against the Calendar v3 REST API — no Google SDK. Auth is the
OAuth refresh-token flow: a one-time consent (documented in setup.md) yields
GOOGLE_OAUTH_CLIENT_ID/SECRET/REFRESH_TOKEN in .env; access tokens are minted
here on demand and cached until expiry.

Reads are ALLOW-tier; writes/deletes are ASK-tier (gate-enforced).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger("alan_t.calendar")

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarAdapter:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 calendar_id: str = "primary"):
        self._client_id, self._client_secret = client_id, client_secret
        self._refresh_token = refresh_token
        self._calendar_id = calendar_id
        self._access_token: str | None = None
        self._expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._client_secret and self._refresh_token)

    async def _token(self, client: httpx.AsyncClient) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        r = await client.post(TOKEN_URL, data={
            "client_id": self._client_id, "client_secret": self._client_secret,
            "refresh_token": self._refresh_token, "grant_type": "refresh_token"})
        r.raise_for_status()
        data = r.json()
        self._access_token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 3600)
        return self._access_token

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._token(client)
            r = await client.request(method, f"{API}{path}",
                                     headers={"Authorization": f"Bearer {token}"}, **kwargs)
            r.raise_for_status()
            return r.json() if r.content else {}

    async def list_events(self, days_ahead: int = 7, query: str | None = None) -> list[dict]:
        now = datetime.now(timezone.utc)
        params = {
            "timeMin": now.isoformat(), "timeMax": (now + timedelta(days=days_ahead)).isoformat(),
            "singleEvents": "true", "orderBy": "startTime", "maxResults": 25,
        }
        if query:
            params["q"] = query
        data = await self._request("GET", f"/calendars/{self._calendar_id}/events", params=params)
        return [{
            "id": e["id"], "summary": e.get("summary", "(untitled)"),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "end": e["end"].get("dateTime", e["end"].get("date")),
            "location": e.get("location"),
        } for e in data.get("items", [])]

    async def create_event(self, summary: str, start_iso: str, end_iso: str,
                           description: str = "", location: str = "") -> dict:
        body = {"summary": summary, "description": description, "location": location,
                "start": {"dateTime": start_iso}, "end": {"dateTime": end_iso}}
        e = await self._request("POST", f"/calendars/{self._calendar_id}/events", json=body)
        return {"id": e["id"], "summary": e.get("summary"), "htmlLink": e.get("htmlLink")}

    async def update_event(self, event_id: str, summary: str | None = None,
                           start_iso: str | None = None, end_iso: str | None = None) -> dict:
        patch: dict = {}
        if summary:
            patch["summary"] = summary
        if start_iso:
            patch["start"] = {"dateTime": start_iso}
        if end_iso:
            patch["end"] = {"dateTime": end_iso}
        e = await self._request("PATCH", f"/calendars/{self._calendar_id}/events/{event_id}",
                                json=patch)
        return {"id": e["id"], "summary": e.get("summary")}

    async def delete_event(self, event_id: str) -> str:
        await self._request("DELETE", f"/calendars/{self._calendar_id}/events/{event_id}")
        return f"deleted event {event_id}"
