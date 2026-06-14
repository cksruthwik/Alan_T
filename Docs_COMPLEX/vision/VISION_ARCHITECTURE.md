# Alan_T — Vision Architecture

Version: 0.1 · Phase: 4 · Governing decision: ADR-006 in [DECISION_LOG.md](../architecture/DECISION_LOG.md)

## The Simplification

v0.1 planned three local models (Qwen-VL for VQA, YOLO for detection, PaddleOCR for text) with three pipelines. v0.2 collapses all of it into one `VisionProvider` port with one Gemini multimodal adapter:

```
image/screenshot/camera frame
        ─▶ VisionProvider.analyze(image, task_prompt) ─▶ structured VisionResult
              MVP adapter: gemini-2.5-flash (fallback gemini-2.5-pro)
              future adapters: qwen-vl / yolo / paddleocr composite — same port
```

`VisionResult` is task-shaped: `{description, ocr_text?, objects?[{label, approx_box}], answer?}` — the port contract is capability-complete so a future composite local adapter slots in without consumer changes.

## Input Sources

| Source | Acquisition | Permission |
|---|---|---|
| User-shared image | chat upload / Telegram photo | ALLOW (user provided it) |
| Screenshot | `capture_screenshot` tool (mss/grim) | ASK — screen content egresses to cloud |
| Camera | `capture_camera` tool (single frame, v4l2/OpenCV) | ASK per capture or session override |
| Browser page | `BrowserSession.screenshot()` | inherits browser task's audit context |
| PDF scanned pages | ingestion OCR fallback | ASK on first use per document batch ([INGESTION_PIPELINE.md](../knowledge/INGESTION_PIPELINE.md) §4) |

No continuous capture loops anywhere — every frame is a discrete, audited, consent-bearing event ([VISION_AGENT.md](../agents/VISION_AGENT.md)).

## Pre-Processing (quota + quality)

1. Downscale to max useful edge (default 1568px — Gemini's effective tiling sweet spot); screenshots of text keep higher floor for OCR legibility.
2. Hash-based session cache: identical frame re-analyzed only if the task prompt differs.
3. Multi-frame requests (e.g., "compare these two screenshots") batch into one model call, not N.

## Consumers

- **Vision agent** — direct user-facing QA/OCR ([VISION_AGENT.md](../agents/VISION_AGENT.md)).
- **Browser agent** — page understanding when DOM digest fails ([BROWSER_AGENT.md](../agents/BROWSER_AGENT.md)).
- **Desktop agent (Phase 6)** — the screenshot→understand→act loop; precision caveat below.
- **Ingestion** — scanned-PDF OCR, image captioning for indexed image files.

## Known Limit & Its Trigger

Gemini's object localization is descriptive/approximate. For VQA, OCR, UI understanding, and "click roughly here" guidance it suffices. If Phase 6 desktop automation proves to need pixel-precise click targets at scale, that is the recorded trigger for a local detector (YOLO-class) adapter behind the same port handling *only* the geometry sub-task — Gemini keeps the semantics. Decision deferred until evidence exists; revisit logged in [BACKLOG.md](../product/BACKLOG.md).

## OCR Output Discipline

Extracted text is returned verbatim (code-blocked) and treated downstream as untrusted external data under the injection rules ([PROMPTS.md](../ai/PROMPTS.md) §6) — a photographed sticky note can carry a prompt injection as easily as a webpage.
