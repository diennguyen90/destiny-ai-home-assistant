# Destiny — Streaming Answers + Thinking Fillers (Design)

Date: 2026-11-17
Status: Approved 2026-11-17
Builds on: [Phase 2 brain design](2026-11-17-phase2-destiny-brain-design.md) (milestone 1 live)

## 1. Intent

Destiny should feel natural to talk to. Today she waits for Claude's whole answer,
then turns all of it into speech, then speaks, which takes about 3.5–6 s. Long "why"
answers feel slow. The family wants:

1. **Streaming:** she starts speaking as soon as the first sentence is ready.
2. **Thinking fillers:** on long questions she says a short, varied phrase right
   away ("Ooh, that's a good question, let me think about it for a second."),
   the way a person does. The family's choice is spoken fillers with variety.
   A fuller personality comes later (milestone 2).

## 2. Goals, non-goals, anti-goals

- **Goals:**
  - Time from the end of the user's speech to her first spoken word should be about 2 s
    or less on long answers.
  - Filler phrases are spoken instantly on Tier 2 or escalated questions.
  - Nothing else about her behaviour changes: routing, caps, history, logging,
    weather and forecast.
- **Non-goals:**
  - Streaming speech-to-text (Whisper stays as is).
  - The custom "Destiny" wake word (a separate project).
  - Personality and profiles (milestone 2).
  - Interrupting her mid-answer ("barge-in").
- **Anti-goals:**
  - Fillers on quick questions, which would make her slower.
  - Fillers stored in Claude's conversation memory.
  - A streaming failure that leaves her silent. She must fall back to the
    current non-streaming path.
  - The same filler twice in a row.

## 3. What exists (verified in HA 2026.11 source)

- **Conversation entities can stream.** `ConversationEntity._attr_supports_streaming` /
  `supports_streaming`, plus `ChatLog.async_add_delta_content_stream(...)`
  (`conversation/chat_log.py:567`).
- **The assist pipeline streams TTS** when the agent supports streaming *and* the TTS
  engine supports streaming input (`assist_pipeline/default_pipeline.py:178-186`). It
  starts speaking once more than **60 characters** have arrived
  (`STREAM_RESPONSE_CHARS = 60`, `default_pipeline.py:66,693`).
- **The HA ElevenLabs TTS streams** (`async_stream_tts_audio`, with
  sentence-boundary detection, `elevenlabs/tts.py:165-209`).
- **The brain** (FastAPI) has `POST /v1/converse` (blocking JSON). The connector
  (`ha/custom_components/destiny`) uses stdlib `brain_client.converse`.

## 4. Approaches considered

- **A. Chunked HTTP stream (NDJSON) from brain to connector into HA's chat-log delta
  stream. Chosen.** It uses HA's native streaming path and needs no device changes.
- **B. WebSocket between brain and connector.** Rejected: more moving parts and no
  benefit for one-way text.
- **C. Keep the blocking answer and play the filler via `assist_satellite.announce`
  while the brain works.** Rejected: it competes with the active pipeline on the
  device and can cut itself off.

## 5. Design

### 5.1 Brain: `POST /v1/converse/stream`

- **Request:**
  - Same body and `X-Destiny-Key` auth as `/v1/converse`.
  - 401 on a bad or missing key, as today.
- **Response:**
  - `200`, `Content-Type: application/x-ndjson`, one JSON object per line.
  - `{"type": "delta", "text": "<more words>"}`, zero or more times.
  - `{"type": "end", "speech": "<full spoken text incl. filler>", "conversation_id": "...", "continue_conversation": bool}`, exactly once, last.
- **Errors:**
  - All errors are reported in-band as a final `end`, never as an HTTP error after
    headers.
  - If nothing was spoken yet, `end.speech` is the existing error, cap or empty line
    and is also sent as one `delta` first, so it gets spoken.

### 5.2 Engine: `Engine.handle_stream(req) -> Iterator[dict]`

The routing, caps, deadline, history and logging are the same as `handle`. These steps differ:

1. **Tier 1 (Haiku)** is still called *blocking* (it's fast, about 1 s). This is needed
   because the escalation tool decides whether to hand off before any text should be spoken.
   - If it answers: emit its text as one `delta`, then `end`.
   - If it escalates: emit a **filler** `delta` immediately, then stream Tier 2.
2. **Tier 2 (Sonnet)** routes, both direct and sticky: emit a **filler** `delta` *before*
   calling the model, then stream Sonnet's text deltas as they arrive.
3. **History:**
   - Append the user turn, the context system message and Sonnet's final assistant
     `content` blocks exactly as returned, as today.
   - **Never append the filler.**
4. **Refusal or empty text after streaming:**
   - If no model text was streamed, emit the refusal or error line.
   - If some text was streamed and the stream then fails, emit `" Sorry, I lost my train of thought."` and end. Don't append that turn to history.
5. **Deadline:**
   - The existing 13.5 s budget applies to the **first model token**, not the whole
     answer. Long answers may take longer to finish speaking.
   - `max_tokens` stays 1024.
6. **Logging:** same records, plus a new nullable `first_token_ms` column. Migrate with
   `ALTER TABLE` if the column is missing. Show `first_token_ms` on the parent page.

### 5.3 Fillers (`brain/destiny_brain/fillers.py`)

- 16–20 short, warm, varied phrases, **each at least 61 characters** so HA starts TTS
  on the filler alone. Spoken style, no symbols. Examples:
  - "Ooh, that's a good question, let me think about it for a second."
  - "Hmm, let me put my thinking cap on for that one, just a moment."
- `pick_filler(device_id) -> str` never repeats any of the last 5 fillers used on that
  device. Kept in memory and thread-safe.
- Fillers go only to the stream and are never sent to Claude.
- The personality layer (milestone 2) will later own this list per profile.

### 5.4 Provider: `ChatProvider.stream(...)`

- Same arguments as `complete`.
- Uses the SDK's streaming helper on the same beta surface and with the same
  parameters as today:
  - `thinking.block_binding.prefix_mismatch_behavior: "drop_block"` with beta
    `thinking-binding-controls-2026-08-01`
  - Sonnet also gets `server-side-fallback-2026-07-01` and `fallbacks="default"`
  - effort, `max_tokens` 1024, per-call timeout
- Yields text deltas and finally returns a `ProviderResult` with the same
  `content` / `usage` / `stop_reason` / `model` fields `complete` returns. Errors map to
  `ProviderError` as today.

### 5.5 HA connector

- `DestinyBrainEntity._attr_supports_streaming = True`.
- `_async_handle_message`:
  - Opens `POST {brain_url}/v1/converse/stream` with HA's shared aiohttp session.
  - Feeds an async generator of assistant deltas into
    `chat_log.async_add_delta_content_stream(...)`. The exact delta dict shape
    comes from the Task 1 spike.
  - Returns the result with the brain's `conversation_id` and `continue_conversation`.
- **Fallbacks:**
  - If the stream can't start (connection refused, non-200, or no first line within
    15 s), call the existing blocking `brain_client.converse` (which already falls back
    to the nap line).
  - If the stream starts and then goes silent for more than 10 s, finish with
    `" Sorry, I lost my train of thought."`.
- Parsing the NDJSON lines is pure Python (`stream_client.py`, no `homeassistant`
  imports) so it can be unit tested in the brain container like `brain_client.py`.

## 6. Testing

- **Brain unit tests (fake streaming provider):**
  - Tier 1 answer yields one delta and no filler.
  - Tier 2 yields the filler first and then the deltas.
  - Escalation yields the filler and then Sonnet's deltas.
  - The filler is never in history.
  - No repeat among the last 5 fillers.
  - All fillers are at least 61 characters.
  - The error, cap and empty paths each yield one delta plus `end`.
  - A mid-stream failure yields the "lost my train of thought" line and no history append.
  - `first_token_ms` is logged.
- **API tests:** NDJSON framing, 401, and `end` always last.
- **Connector tests (stdlib stub server):**
  - Delta parsing.
  - Fallback to the blocking call when the stream can't start.
  - The idle-timeout line.
- **Live:**
  - Voice PE, "why is the sky blue?": the filler is heard within about 2 s and the
    answer follows without a gap.
  - Quick question: no filler.
  - Pipeline debug and the parent page show `first_token_ms`.
  - `scripts/smoke_test.py` still passes 7/7. It uses the blocking path, which is kept.

## 7. Left to the builder

- Exact filler wording, within the rules above.
- NDJSON line buffering details.
- How `stream()` is shared with `complete()` internally.
- Parent-page column placement.
