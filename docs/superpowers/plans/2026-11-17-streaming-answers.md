# Streaming Answers + Thinking Fillers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Destiny starts speaking within about 2 s on long answers. She says a varied filler instantly on Tier 2 questions and then streams Claude's answer through Home Assistant into ElevenLabs.

**Architecture:**
- A new brain endpoint `POST /v1/converse/stream` emits NDJSON `delta` and `end` events from `Engine.handle_stream`.
- `Engine.handle_stream` reuses the existing routing, caps, history and logging, and adds `ChatProvider.stream`.
- The HA connector declares streaming support and feeds the deltas into `ChatLog.async_add_delta_content_stream`. If the stream fails, it falls back to the blocking endpoint.

**Tech Stack:** Python 3.12, FastAPI `StreamingResponse`, the anthropic SDK 1.17.0 streaming helper, aiohttp (HA's session), pytest, HA 2026.11.0.

**Spec:** [docs/superpowers/specs/2026-11-17-streaming-answers-design.md](../specs/2026-11-17-streaming-answers-design.md)

## Global Constraints

- Every model call keeps today's parameters exactly:
  - `client.beta.messages.*`
  - `thinking={"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}`
  - betas include `"thinking-binding-controls-2026-08-01"`
  - Sonnet also gets `"server-side-fallback-2026-07-01"` and `fallbacks="default"`
  - `output_config={"effort": ...}`, `max_tokens=1024`
  - `tool_choice` `auto` only when tools are given
  - per-call timeout via `with_options`
- Fillers are at least 61 characters each, there are 16–20 of them, and none repeats among the last 5 on a device. They are never sent to Claude or stored in history.
- NDJSON events, exactly:
  - `{"type":"delta","text":str}`
  - `{"type":"end","speech":str,"conversation_id":str,"continue_conversation":bool}`
  - `end` is always the last line and appears exactly once.
- The mid-stream failure line is verbatim: `" Sorry, I lost my train of thought."` (with a leading space).
- The existing blocking `/v1/converse` and its behaviour stay unchanged. The smoke test still passes 7/7.
- The 13.5 s deadline applies to the first model token in streaming mode.
- Secrets: never read `.env`. Never `git add -A`. Never add `.claude/`. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tests:
  - Brain: `docker compose run --rm --no-deps brain pytest -q`
  - Host: `python -X dev -W error -m unittest discover -s tests`

## Review Focus

1. **Stream dies mid-answer** (the API drops, or HA cancels because the user walked away). She speaks the "lost my train of thought" line, nothing is appended to history, and the brain doesn't keep billing after the client disconnects. Test in Tasks 4 and 5.
2. **Connector can't reach the stream endpoint** (an older brain or a crash). It falls back to the blocking call and then the nap line, and is never silent. Test in Task 6.
3. **A refusal or an empty answer after the filler was already spoken.** The refusal line follows the filler naturally, and nothing is stored. Test in Task 4.
4. **The same device asks quickly in a row.** No filler repeats among the last 5, and two devices don't share or block each other's filler history. Test in Task 2.
5. **Soft cap or hard cap reached during a streaming request.** The same lines as blocking mode, delivered as one delta plus `end`. Test in Task 4.

---

### Task 1: Spike — HA streaming delta contract

**Files:** Create `docs/superpowers/notes/2026-11-17-ha-streaming-agent.md`

- [ ] **Step 1:** In container `destiny-homeassistant`, read `conversation/chat_log.py` (around `async_add_delta_content_stream`, line 567), the delta TypedDicts (`AssistantContentDeltaDict` or equivalent), and how `entity.py` and the pipeline use `supports_streaming`. Also read one in-tree streaming agent (e.g. `components/anthropic/entity.py` or `ollama`) to see a minimal working pattern, including how the final result and `continue_conversation` are produced.
- [ ] **Step 2:** Write the notes with the exact signatures, delta dict keys (`role`, `content`, …), the required first delta, how to finish, how to build `ConversationResult`, and a minimal skeleton of a streaming `_async_handle_message` fed by an async iterator. Cite file:line.
- [ ] **Step 3:** Commit `docs: HA streaming agent contract notes`.

### Task 2: Fillers and the `first_token_ms` column

**Files:**
- Create `brain/destiny_brain/fillers.py`, `brain/tests/test_fillers.py`
- Modify `brain/destiny_brain/store.py`, `brain/tests/test_store.py`

**Interfaces:**
- Produces:
  - `fillers.FILLERS: tuple[str, ...]`
  - `fillers.FillerPicker(recent: int = 5)` with `.pick(device_id: str | None) -> str` (thread-safe; `None` device uses the key `"_"`)
  - `RequestRecord.first_token_ms: int | None = None`, persisted
  - `Store.init()` migrates an existing DB by adding the column if it's missing

- [ ] **Step 1: Failing tests:**
  - `test_filler_count_and_length`: 16–20 fillers, each at least 61 characters
  - `test_fillers_spoken_style`: no `*#_[]{}<>~` characters and no emoji
  - `test_no_repeat_in_last_five`: 200 picks on one device; no pick appears among the previous 5
  - `test_devices_independent`
  - `test_store_migrates_first_token_ms`: create the old schema without the column, then `init()`; logging `first_token_ms=420` round-trips
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them;** they pass, and so does the full suite.
- [ ] **Step 5: Commit** `feat(brain): thinking fillers and first-token timing column`.

### Task 3: Provider streaming

**Files:** Modify `brain/destiny_brain/providers/base.py`, `providers/anthropic_provider.py`, `brain/tests/test_anthropic_provider.py`

**Interfaces:**
- Produces: `ChatProvider.stream(*, model, system, messages, tools, effort, max_tokens=1024, timeout=None) -> Iterator[str]`, a generator yielding text deltas. Its `return` value (via `StopIteration.value`) is a `ProviderResult`. Errors raise `ProviderError(kind)`, mapped as in `complete`.

- [ ] **Step 1: Failing tests,** with a fake client whose `beta.messages.stream(...)` context manager yields text events and exposes `get_final_message()`:
  - The kwargs are identical to `complete` (same thinking, betas and fallbacks per model)
  - The deltas are yielded in order
  - The final `ProviderResult.content` is the `model_dump()` blocks
  - The usage is mapped
  - An exception mid-stream maps to `ProviderError`
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement** `stream` with the SDK's `client.beta.messages.stream(...)`. Check the event and text-delta attribute names in the installed 1.17.0 package; don't guess. Share the kwargs-building code with `complete`.
- [ ] **Step 4: Run them;** they pass.
- [ ] **Step 5: Commit** `feat(brain): streaming provider calls`.

### Task 4: `Engine.handle_stream`

**Files:** Modify `brain/destiny_brain/engine.py`, `brain/tests/test_engine.py`, `brain/tests/fakes.py`

**Interfaces:**
- Consumes: `FillerPicker`, `ChatProvider.stream`, the existing routing, caps and store.
- Produces: `Engine.handle_stream(req: ConverseRequest) -> Iterator[dict]`, which yields NDJSON event dicts per the Global Constraints. The final event is `end`. It never raises. It holds a `FillerPicker`, injectable via constructor kwarg `fillers=None`.

- [ ] **Step 1: Failing tests:**
  - `test_stream_tier1_single_delta_no_filler`
  - `test_stream_tier2_filler_then_deltas`
  - `test_stream_escalation_filler_then_sonnet`
  - `test_stream_history_excludes_filler`: next request's messages contain no filler text
  - `test_stream_end_speech_is_full_text`
  - `test_stream_midstream_failure_lost_line_no_history`
  - `test_stream_refusal_after_filler`
  - `test_stream_empty_hard_cap_soft_cap_paths`
  - `test_stream_logs_first_token_ms`
  - `test_stream_generator_close_stops_provider`: closing the generator early closes the provider stream, so no further billing (Review Focus 1)
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.** Refactor the shared steps (resolve the conversation, caps, build the request, append to history, log) so `handle` and `handle_stream` don't duplicate logic. The `handle` tests must stay green unchanged.
- [ ] **Step 4: Run them;** they pass, and so does the full suite.
- [ ] **Step 5: Commit** `feat(brain): streaming engine with thinking fillers`.

### Task 5: `/v1/converse/stream` endpoint

**Files:** Modify `brain/destiny_brain/app.py`, `templates/parent.html`, `brain/tests/test_api.py`

- [ ] **Step 1: Failing tests:**
  - 401 without the key
  - NDJSON lines parse, with `end` last and exactly once
  - Content type is `application/x-ndjson`
  - When the client disconnects early, the engine generator is closed
  - The parent page shows a `first_token_ms` column
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement** with `StreamingResponse` iterating `handle_stream` in a thread. Use `iterate_in_threadpool`, or an equivalent that propagates close.
- [ ] **Step 4: Run them;** they pass.
- [ ] **Step 5: Commit** `feat(brain): NDJSON streaming converse endpoint`.

### Task 6: Connector streaming and fallback

**Files:**
- Create `ha/custom_components/destiny/stream_client.py` (pure Python) and `brain/tests/test_connector_stream.py`
- Modify `ha/custom_components/destiny/conversation.py`

**Interfaces:**
- Consumes: the Task 1 notes, the Task 5 endpoint, and the existing `brain_client.converse`.
- Produces: `stream_client.parse_ndjson_lines(chunks: Iterable[bytes]) -> Iterator[dict]`, which handles lines split across chunks and skips blank or garbled lines. Also `LOST_LINE = " Sorry, I lost my train of thought."`.

- [ ] **Step 1: Failing tests** for the parser: split chunks, multiple events per chunk, garbled lines skipped, and a stream ending without `end` reported so the caller can append `LOST_LINE`.
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement** the parser. Then implement the entity:
  - `_attr_supports_streaming = True`
  - An aiohttp POST via `async_get_clientsession(hass)`, with 15 s to the first line and 10 s idle between lines
  - An async delta generator into `chat_log.async_add_delta_content_stream`, using the exact shapes from the Task 1 notes
  - The result carries the brain's `conversation_id` and `continue_conversation`
  - If the stream can't start, fall back to `brain_client.converse` in the executor
- [ ] **Step 4: Run the tests;** they pass. Then `docker compose up -d homeassistant brain`. The HA logs must show no tracebacks for `destiny`.
- [ ] **Step 5: Commit** `feat(ha): stream brain answers into the assist pipeline`.

### Task 7: Docs and live verification (controller and family)

- [ ] **Step 1:** Update `docs/project-log.md`, `docs/troubleshooting.md` (filler explained, the "lost my train of thought" line) and `README.md` (spec link). Commit.
- [ ] **Step 2:** Run the smoke test: 7/7.
- [ ] **Step 3: Voice PE checks.**
  - "Why is the sky blue?": the filler is heard within about 2 s, and the answer follows without a long gap.
  - "Who wrote Charlotte's Web?": no filler.
  - Ask three long questions in a row: three different fillers.
  - Record the pipeline debug timings and `first_token_ms` from the parent page in the project log.
- [ ] **Step 4:** Merge to master and push. The family has approved pushes for this project.
