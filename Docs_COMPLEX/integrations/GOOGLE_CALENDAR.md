# Integration — Google Calendar

Phase: 2+ · Port: `CalendarProvider` · Adapter: `adapters/google_calendar/`
Consumer: Calendar agent (thin — [AGENTS.md](../architecture/AGENTS.md) roster)

## Port Surface

```python
class CalendarProvider(Protocol):
    async def list_events(self, range: TimeRange, calendar: str = "primary") -> list[Event]
    async def get_event(self, event_id: str) -> Event
    async def create_event(self, draft: EventDraft) -> Event
    async def update_event(self, event_id: str, patch: EventPatch) -> Event
    async def delete_event(self, event_id: str) -> None
    async def free_busy(self, range: TimeRange) -> list[BusyInterval]
```

Core `Event` type is provider-neutral (id, title, start/end with tz, location, attendees, recurrence rule, source_link). Outlook (`OutlookAdapter`) is the planned second implementation per PRD FR-10 — the port is designed against both APIs' common ground from day one (recurrence is the hard part; the port carries RFC 5545 RRULE strings, both APIs can).

## Auth

- OAuth 2.0 installed-app flow, one-time browser consent at setup (`alan auth google-calendar` CLI), scopes: `calendar.events` only — not full Google account.
- Implementation rides **gcsa** (Google Calendar Simple API — ADR-015) rather than raw `googleapiclient`: recurrence and OAuth ergonomics for free; the adapter stays a thin mapping to the port.
- Refresh token encrypted (Fernet) in Postgres ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §4); never in env or logs.
- **This is a separate Google identity from the AI Studio API key** — Gemini quota and calendar access are unrelated credentials; revoking one doesn't touch the other.

## Permission Mapping

- `calendar_read` / `free_busy` → ALLOW (read-only, user's own data, no egress beyond Google which already has it).
- `calendar_write` (create/update/delete) → ASK with full event preview ("Create: 'Dentist', Fri 2026-06-20 14:00–15:00") — external, visible-to-others (attendees!) actions. Events with attendees outside the user get an extra-explicit preview line; Alan_T sending meeting invites to other humans is the kind of action that must never surprise.

## Behaviors & Edge Rules

- Natural-language times resolve in the user's configured timezone; ambiguity ("Friday" when it's Friday) → clarify, not guess — wrong calendar writes erode trust faster than almost any other failure.
- Recurring events: modifications ask "this event or the series?" explicitly, mirroring the UI convention users know.
- Conflict awareness: `create_event` runs `free_busy` first and mentions clashes in the ASK preview.
- Scheduling tasks ("find 2h for X this week") combine `free_busy` + user preference memories (e.g., "no meetings before 10:00" — [MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md) kind `preference`).

## Failure Posture

Token expired/revoked → honest "calendar access needs re-auth, run `alan auth google-calendar`" — degraded flag, no retry loop against a dead token. API quota (generous for one user) treated as transient with backoff.
