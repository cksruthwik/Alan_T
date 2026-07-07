---
name: schedule_block
description: >
  Find a free slot and book a calendar block for a task or meeting. Use when
  the user asks to "schedule / block time / put X on my calendar". NOT for
  merely listing events — calendar_list answers that directly.
required_tools: [calendar_list, calendar_create]
role_hint: CHAT
version: 1
---

1. calendar_list the relevant day(s) to see what's already booked.
2. Pick the earliest sensible free slot matching the user's constraints
   (default 60 minutes, working hours, respect stated preferences from memory).
3. Propose the slot to the user in one line, then calendar_create it — the
   create is ASK-tier, so the approval prompt IS the confirmation.
4. Confirm with the event's date, time, and title once created.
