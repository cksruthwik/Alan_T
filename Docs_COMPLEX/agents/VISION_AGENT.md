# Vision Agent

Phase: 4 · Model role: `VISION` (`gemini-2.5-flash` → `gemini-2.5-pro`) — single multimodal model replaces the v0.1 local stack (ADR-006)
Architecture: [VISION_ARCHITECTURE.md](../vision/VISION_ARCHITECTURE.md)

## Responsibility

Visual inputs → answers: user-shared images, screenshots, camera frames. Also serves Browser/Desktop agents as their "eyes" when structural data (DOM/accessibility APIs) is insufficient.

## Tools

`analyze_image` (ALLOW — user provided the image) · `capture_screenshot` (ASK) · `capture_camera` (ASK). Captures are ASK because the frame leaves the machine for the cloud — consent per capture, or per-session via session override ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md) §2).

## Behaviors

- **Visual QA:** `vision_qa.j2` discipline — describe what is seen, then answer; uncertainty stated ("the text is partially cut off").
- **OCR:** extracted text returned verbatim in code blocks, separated from interpretation. OCR text entering prompts downstream is injection-delimited like any external content ([PROMPTS.md](../ai/PROMPTS.md) §6) — a screenshot can contain hostile instructions too.
- **Error-screenshot debugging** (the flagship Phase 4 scenario): OCR the error → correlate with indexed code if the repo is known (`code_search` handoff) → grounded fix suggestion.
- **Object detection / UI element location:** Gemini returns described locations and approximate boxes — good enough for QA and agent guidance. If a future use needs precise geometry (desktop click targeting), that's the recorded trigger for a local YOLO adapter behind the same `VisionProvider` port, not a redesign.
- **Camera:** single-frame capture-and-analyze on request. No continuous monitoring — not built, deliberately (an always-on camera loop is a different privacy product).

## Service Role for Other Agents

Browser/Desktop agents call VISION through the same port with task-scoped prompts ("locate the Submit button region"). Those calls inherit the *calling task's* audit context — vision-as-a-service doesn't launder action provenance.

## Quotas

Images are token-expensive on free tiers. The agent downscales images to the minimum useful resolution before sending, caches analyses by image hash within a session, and the screenshot→action loops in Phases 5–6 prefer DOM/accessibility observation with vision as fallback ([BROWSER_AGENT.md](BROWSER_AGENT.md)).
