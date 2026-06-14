# Alan_T — Voice Architecture

Version: 0.1 · Phase: 2 · Governing decision: ADR-007 in [DECISION_LOG.md](../architecture/DECISION_LOG.md)

Two distinct paths with different latency/quality trade-offs. Both behind ports (`STTProvider`, `TTSProvider`, `LiveVoiceProvider`) — Kokoro/Faster-Whisper/Moshi remain future local swaps without core change.

## Path A — Turn-Based Voice (voice notes, push-to-talk)

```
audio in ─▶ STTProvider (Groq whisper-large-v3-turbo)
        ─▶ transcript ─▶ normal chat turn (W1, full agent/tool/memory machinery)
        ─▶ answer text ─▶ TTSProvider (Gemini TTS) ─▶ audio out (+ text always shown)
```

- Strengths: full Alan_T capability (tools, RAG, memory) since it's just a chat turn; accuracy (turbo Whisper); works async (Telegram voice notes).
- Latency budget: STT < 1 s (turbo) + first-token < 1.5 s + TTS-first-chunk < 1 s → speech reply starting ≈ 3–4 s. Meets the amended < 3 s NFR target for short answers; long answers start speaking at the **first sentence boundary** while the rest generates (streaming pipeline, not generate-then-speak).
- `whisper-large-v3` (non-turbo) swap for accuracy-critical transcription jobs (e.g., transcribing a recorded meeting for ingestion) — that's a role-param config, not new code.

## Path B — Live Voice (Gemini Live API)

```
mic stream ◀─WS─▶ api /voice/live ◀─WS─▶ Gemini Live session
                       │ session start: inject persona + recalled memories
                       │ tool calls: bridged through the SAME permission gate
                       └ session end: transcript persisted → fact extraction
```

- Native speech-to-speech: natural latency, interruption support (the PRD's Moshi goals) with zero local model ops.
- **Capability asymmetry, stated honestly:** the live session's model is Gemini's, not the role registry's — Groq-routed roles don't apply mid-conversation. Tool access works (Live API function calling → our gate) but heavy multi-step work degrades the conversational flow; the live path is for *conversation*, and long tasks are handed to the task graph with a spoken "I'll work on that and message you."
- Privacy note: continuous mic audio streams to Google for the session duration — live mode is explicitly user-initiated per session, never auto-started ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §5).
- **The one place a single vendor sits on a default — and it's a choice, not lock-in:** `LIVE_VOICE` defaults to Gemini-native for quality/latency, but the provider-neutral escape is Path A's composed `STT → CHAT → TTS` pipeline, which runs on any profile's models (including fully local). Selecting it is a registry edit; the system degrades to it gracefully rather than hard-failing. This is the honest constraint recorded in [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §8 and ADR-017.

## Implementation: Pipecat (ADR-014)

Both paths are built as **Pipecat** pipelines inside the voice adapter layer — transport (WebSocket/WebRTC), VAD, interruption handling, and streaming STT→LLM→TTS orchestration come from the framework, which natively supports Gemini Live and Groq Whisper. The `STTProvider`/`TTSProvider`/`LiveVoiceProvider` ports stand unchanged; Pipecat is the engine behind them. The async Telegram voice-note flow (W4) may bypass Pipecat — a file-in/file-out STT→chat→TTS sequence needs no realtime machinery.

## Shared Rules

1. Transcripts are first-class: both paths persist text into `conversation_turns` (modality flags) — voice conversations are searchable, summarizable, memory-feeding like text.
2. TTS output cached by (text-hash, voice) for repeated phrases (greetings, confirmations) — small quota saver.
3. Audio blobs are not stored by default (transcripts are); voice-note originals kept 7 days for re-transcription, then dropped.
4. Wake-word/always-listening: **not in scope** — push-to-talk and explicit session start only. An always-on microphone is a different threat model and a different product.

## Future Local Swap (the ADR-007 escape hatch)

Faster-Whisper (STT) and Kokoro (TTS) adapters restore fully-local turn-based voice when hardware justifies it; Path A's pipeline doesn't change. Path B has no local equivalent on the horizon (Moshi re-evaluation is the trigger) — losing live mode is the accepted cost of going local later.
