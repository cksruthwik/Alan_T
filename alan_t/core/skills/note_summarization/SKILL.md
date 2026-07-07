---
name: note_summarization
description: >
  Summarize one of the user's notes or documents into a tight digest.
  Use when the user asks to summarize, condense, or "give me the gist of"
  something in their own files. NOT for summarizing text pasted in chat —
  the agent can do that directly.
required_tools: [search_knowledge]
role_hint: SUMMARIZER
version: 1
---

1. Retrieve the relevant note(s) with search_knowledge using the user's topic words.
2. If nothing is found, say so plainly — never summarize from imagination.
3. Summarize into: one-line TL;DR, 3–7 bullet key points, and any open
   questions/action items found in the note.
4. Cite each summarized source by its vpath.
