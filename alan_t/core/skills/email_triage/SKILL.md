---
name: email_triage
description: >
  Triage the user's inbox: group unread mail by urgency, summarize each thread
  in one line, propose which need replies today. Use when the user asks to
  "check/triage/summarize my email/inbox". NOT for sending a specific email
  the user already dictated — that's a direct email_send.
required_tools: [email_list, email_read]
role_hint: CHAT
version: 1
---

1. List unread mail (email_list unread_only=true, limit 15).
2. Read only the messages whose subject/sender suggests action; skip obvious
   newsletters and receipts.
3. Report three buckets: needs reply today / can wait / ignore-archive, with a
   one-line summary each and sender names.
4. Offer to draft replies for the "needs reply today" bucket — drafting is
   free, sending needs approval.
