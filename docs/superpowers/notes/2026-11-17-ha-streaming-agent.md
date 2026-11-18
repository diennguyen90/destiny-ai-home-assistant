# HA streaming conversation agent contract (HA 2026.11.0)

Source: container `destiny-homeassistant`, `/usr/src/homeassistant/homeassistant/components/`.
Paths below are relative to that dir.

## 1. Opt in

- `conversation/entity.py:21,25-27`: `_attr_supports_streaming = False` default; `supports_streaming` property returns it. Set `_attr_supports_streaming = True` on `DestinyConversationEntity` (ollama does at `ollama/conversation.py:39`).
- `assist_pipeline/default_pipeline.py:178-186` `supports_streaming_response`: True only if the TTS stream `supports_streaming_input` (ElevenLabs should) AND `intent_agent.supports_streaming`.
- `conversation/__init__.py:187` exposes it via `agent.supports_streaming`.

## 2. Delta types (`conversation/chat_log.py:348-366`)

```python
class AssistantContentDeltaDict(TypedDict, total=False):
    role: Literal["assistant"]
    content: str | None
    thinking_content: str | None
    tool_calls: list[llm.ToolInput] | None
    native: Any
```
Plain `str` deltas are NOT accepted; each delta is a dict. Text delta = `{"content": "some text"}`.

## 3. `ChatLog.async_add_delta_content_stream` (chat_log.py:567-690)

```python
async def async_add_delta_content_stream(
    self, agent_id: str,
    stream: AsyncIterable[AssistantContentDeltaDict | ToolResultContentDeltaDict],
) -> AsyncGenerator[AssistantContent | ToolResultContent]
```
- It is an async GENERATOR: it does nothing until iterated. Must be consumed, e.g. `async for _ in chat_log.async_add_delta_content_stream(...): pass` (ollama collects in a list comprehension, ollama/entity.py:299-306).
- Delta without `role` (chat_log.py:594-630): appends `content` (concatenated, `None` ignored), thinking, tool_calls to the current message, then calls `delta_listener(chat_log, delta)`.
- Delta with `role: "assistant"` (:633-): flushes any pending message into the log, starts a new one, and also fires the listener with the role delta.
- On stream end (:677-690) the pending message is flushed and appended to the chat log as an `AssistantContent`. No explicit "finish" delta is needed: just let the iterator end.
- `agent_id` should be `user_input.agent_id` (in-tree agents use `self.entity_id`; the existing code uses `user_input.agent_id`).

## 4. Must the first delta be `{"role": "assistant"}`? YES, for TTS streaming

`default_pipeline.py:637-668` `chat_log_delta_listener`: `chat_log_role` starts `None` and is only set from a delta's `role` key. Then `if chat_log_role != "assistant": return` (~:664-665), so content deltas received before any role delta are DROPPED from the TTS queue and from the streaming trigger. Chat log accumulation itself would still work, but pipeline streaming would not. So the first yielded delta must be `{"role": "assistant"}` (it may also carry `content`; the listener reads `role` first, then `content`; ollama puts role and first content in the same chunk, ollama/entity.py:180-182). Safest for us: yield `{"role": "assistant"}` first, then `{"content": text}` per NDJSON delta.

## 5. When TTS streaming actually starts (default_pipeline.py:66,672-720)

- `STREAM_RESPONSE_CHARS = 60` (:66). Content deltas are counted; streaming starts when cumulative chars `> 60` (strictly), or when a tool call arrives after some text (:684-693). Streamed responses are not cached, hence the threshold.
- Until then content is queued; at the trigger the queue is concatenated, `tts_stream.async_set_message_stream(generator)` is called (:719-720), `_streamed_response_text = True`, and an INTENT_PROGRESS `tts_start_streaming` event fires (:698-706).
- Consequence: a filler must be >= 61 chars (matches global constraint) so the first delta alone triggers streaming. Short answers (<=60 chars total) take the normal non-streamed path using the result speech (default_pipeline.py:1013, `async_set_message(tts_input)`).
- After `async_converse` returns, if streaming started the pipeline puts `None` on the TTS queue to end it (:842-843). Nothing for the agent to do.
- Between assistant messages the pipeline inserts a " " into TTS (:652-661).

## 6. Result and `continue_conversation`

- `ChatLog.continue_conversation` (chat_log.py:393-411) is a HEURISTIC: last content is assistant and ends with `?`, `;`, or the fullwidth `？`. It is only used by `conversation.async_get_result_from_chat_log`.
- `conversation/util.py:18-47` `async_get_result_from_chat_log(user_input, chat_log)`: builds an `IntentResponse`, sets speech to the last assistant content, and `continue_conversation=chat_log.continue_conversation`. It raises `HomeAssistantError` (`no_response`) if the last chat-log content is not an `AssistantContent` (e.g. no deltas arrived). Ollama returns it directly (ollama/conversation.py:88).
- DO NOT use it for Destiny: the brain decides `continue_conversation` explicitly in the NDJSON `end` event. Build the result by hand, as today:
  ```python
  response = intent.IntentResponse(language=user_input.language)
  response.async_set_speech(end["speech"])
  return conversation.ConversationResult(
      response=response,
      conversation_id=end.get("conversation_id") or chat_log.conversation_id,
      continue_conversation=bool(end.get("continue_conversation", False)),
  )
  ```
- The pipeline reads `conversation_result.continue_conversation` (default_pipeline.py:887-888) to keep the agent for the follow-up turn; it does not read `chat_log.continue_conversation`.
- Pipeline fallback (default_pipeline.py:838-846): if after `async_converse` the last chat-log content is still `user` and speech is non-empty, the pipeline appends the speech as assistant content itself. So an agent that yields no deltas still works through the result speech. Conversely, do NOT also call `async_add_assistant_content_without_tools` after streaming deltas (duplicates).

## 7. Final speech vs streamed text

TTS gets the streamed deltas (not `end.speech`) when streaming started. `end.speech` matters for the response object, non-streamed path and history. Keep `end.speech` equal to the concatenation of deltas (brain contract) so UI, chat log and audio agree. Mid-stream failure: the brain emits the verbatim `" Sorry, I lost my train of thought."` as a normal text delta; HA needs no special handling.

## 8. Minimal skeleton for Task 6

```python
from collections.abc import AsyncGenerator

_attr_supports_streaming = True

async def _async_handle_message(self, user_input, chat_log):
    payload = {...}  # unchanged
    end: dict = {}

    async def _deltas() -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
        nonlocal end
        yield {"role": "assistant"}               # REQUIRED first, see section 4
        async for event in brain_client.converse_stream(url, key, payload):  # async iterator of NDJSON dicts
            if event["type"] == "delta":
                yield {"content": event["text"]}
            elif event["type"] == "end":
                end = event

    async for _ in chat_log.async_add_delta_content_stream(user_input.agent_id, _deltas()):
        pass

    speech = end.get("speech", "")
    response = intent.IntentResponse(language=user_input.language)
    response.async_set_speech(speech)
    return conversation.ConversationResult(
        response=response,
        conversation_id=end.get("conversation_id") or chat_log.conversation_id,
        continue_conversation=bool(end.get("continue_conversation", False)),
    )
```
Notes: `conversation.AssistantContentDeltaDict` is used as such at ollama/entity.py:156. If the brain call fails before `end`, raise `HomeAssistantError` rather than returning an empty result. The brain client must be natively async (aiohttp via `async_get_clientsession`) or bridge a blocking executor-thread stream into an `asyncio.Queue` with `hass.loop.call_soon_threadsafe`; deltas must reach the loop as they arrive, not after the call returns.

## 9. Open items to verify live

- ElevenLabs `supports_streaming_input` is True in this install (otherwise `supports_streaming_response` is False and TTS never streams).
- Satellite flow: confirm TTS audio starts before the `end` event arrives.
