---
name: memory_recap
description: >
  Recap what Alan_T remembers about the user on a topic (preferences, goals,
  projects, facts). Use when the user asks "what do you know/remember about
  me/X" or wants stored memory reviewed or corrected. NOT for questions about
  file contents — that's search_knowledge territory.
required_tools: [recall_memory]
role_hint: CHAT
version: 1
---

1. Recall stored facts with recall_memory using the user's topic (or broad
   recall if they asked for everything).
2. Present them grouped (preferences / goals / projects / facts), each with
   its noted-on date when available.
3. Invite corrections: anything wrong or stale can be forgotten or replaced —
   the user owns this memory.
