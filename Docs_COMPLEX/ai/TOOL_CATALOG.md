# Alan_T — Tool Catalog

Version: 0.1
Status: Living document — every tool MUST be registered here and in the permission config before first use.

## 1. Tool Contract

```python
class ToolSpec:
    name: str                  # unique, snake_case
    description: str           # written for the model — precise, includes when NOT to use
    parameters: JSONSchema     # validated before execution
    permission_tier: Tier      # ALLOW | ASK | DENY  (see TOOL_PERMISSIONS.md)
    side_effects: SideEffect   # NONE | LOCAL_READ | LOCAL_WRITE | NETWORK | EXTERNAL_ACTION
    agent_scope: list[str]     # which agents may carry this tool
```

- Tools are core functions calling ports — a tool never imports a provider SDK directly.
- **Skills consume tools, they don't replace them** ([SKILLS.md](SKILLS.md)): a skill's `required_tools` are entries in this catalog, and every call a skill makes passes the same gate. A skill can orchestrate `search_knowledge` + `calendar_write`, but the `calendar_write` ASK interrupt still fires. Registering a tool here is the prerequisite for any skill naming it.
- Every execution: schema-validate args → permission check → execute with timeout → audit log entry → structured result (success or typed error) back to the model.
- Tool results returned to models are size-capped (default 4k tokens) with overflow summarized via SUMMARIZER.

## 2. Catalog

### Knowledge & Memory (Phase 1)

| Tool | Tier | Side effects | Description |
|---|---|---|---|
| `search_knowledge` | ALLOW | NONE | hybrid search over ingested corpus; returns chunks + sources |
| `read_source` | ALLOW | LOCAL_READ | fetch full content of an ingested source by path/id |
| `remember_fact` | ALLOW | LOCAL_WRITE | store an explicit user-stated fact in long-term memory |
| `recall_memory` | ALLOW | NONE | query long-term memory store |
| `forget_memory` | ASK | LOCAL_WRITE | delete a memory item (user-initiated only) |
| `ingest_path` | ASK | LOCAL_READ+NETWORK | add a new folder/file to the ingestion set (sends content to embedding API — hence ASK) |

### Productivity (Phase 2+)

| Tool | Tier | Side effects | Description |
|---|---|---|---|
| `calendar_read` | ALLOW | NETWORK | list/read events in range |
| `calendar_write` | ASK | EXTERNAL_ACTION | create/modify/delete events |
| `notes_read` / `notes_search` | ALLOW | LOCAL_READ | read/search notes via NotesProvider |
| `notes_write` | ASK | LOCAL_WRITE | create/update a note |
| `set_reminder` | ALLOW | LOCAL_WRITE | schedule a reminder via Scheduler |

### Code (Phase 3)

| Tool | Tier | Side effects | Description |
|---|---|---|---|
| `code_search` | ALLOW | NONE | semantic + symbol search over indexed repos |
| `read_file_lines` | ALLOW | LOCAL_READ | read a file slice from an indexed repo |
| `repo_overview` | ALLOW | NONE | structure/dependency summary of an indexed repo |

### Vision (Phase 4)

| Tool | Tier | Side effects | Description |
|---|---|---|---|
| `analyze_image` | ALLOW* | NETWORK | VQA/OCR/detection on a user-provided image (*user provided it — implied consent) |
| `capture_screenshot` | ASK | NETWORK | grab screen + analyze (screen content leaves machine) |
| `capture_camera` | ASK | NETWORK | camera frame + analyze |

### Browser (Phase 5)

| Tool | Tier | Side effects | Description |
|---|---|---|---|
| `browser_navigate` / `browser_extract` | ASK→ALLOW¹ | NETWORK | open URL, read/extract content |
| `browser_interact` | ASK | EXTERNAL_ACTION | click/fill/submit on a page |
| `web_research` | ALLOW | NETWORK | delegated research via WEB_AGENT (groq/compound) |

¹ read-only browsing can be promoted to ALLOW per-domain via permission config.

### Desktop (Phase 6)

| Tool | Tier | Side effects | Description |
|---|---|---|---|
| `desktop_screenshot` | ASK | NETWORK | screen capture for the action loop |
| `desktop_input` | ASK | EXTERNAL_ACTION | mouse/keyboard actions (dry-run mode available) |
| `app_launch` | ASK | EXTERNAL_ACTION | start an application |
| `window_manage` | ASK | EXTERNAL_ACTION | focus/move/resize windows |

### Communication (Phase 8)

| Tool | Tier | Side effects | Description |
|---|---|---|---|
| `send_telegram` | ASK² | EXTERNAL_ACTION | send message/file to the user's own Telegram |
| `notify` | ALLOW | LOCAL_WRITE | queue an in-app notification |

² messages to the owner can be promoted to ALLOW; messages to anyone else are DENY (single-user system).

### Never-Tools (DENY by design)

`shell_exec` (arbitrary commands), `send_email_external`, payment/purchase actions, credential reads. These are not "ASK with scary warnings" — they are absent from the registry. Adding one requires an ADR.

## 3. Registration Checklist (for every new tool)

1. Entry in this file with tier rationale.
2. `ToolSpec` in code with JSON schema.
3. Tier set in `config/permissions.yaml` ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)).
4. Audit-log fields verified.
5. Unit test with fake port + one contract test.
6. Description reviewed against prompt-injection misuse ("could a hostile document trick the model into harmful use of this tool?").
