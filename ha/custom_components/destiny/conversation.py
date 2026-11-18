"""Destiny brain conversation entity."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Literal

import aiohttp
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import brain_client
from .stream_client import LOST_LINE, NdjsonDecoder

_LOGGER = logging.getLogger(__name__)

FIRST_LINE_TIMEOUT = 15.0
IDLE_TIMEOUT = 10.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DestinyConversationEntity(entry)])


class DestinyConversationEntity(conversation.ConversationEntity):
    _attr_has_entity_name = False
    _attr_name = "Destiny brain"
    _attr_supports_streaming = True

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = entry.entry_id

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return MATCH_ALL

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        url = self._entry.data["brain_url"]
        key = self._entry.data["shared_key"]
        payload = {
            "text": user_input.text,
            "conversation_id": user_input.conversation_id,
            "device_id": user_input.device_id,
            "satellite_id": user_input.satellite_id,
            "language": user_input.language,
        }
        session = async_get_clientsession(self.hass)
        resp = None
        pending: list[dict] = []
        decoder = NdjsonDecoder()
        chunks = None
        try:
            async with asyncio.timeout(FIRST_LINE_TIMEOUT):
                resp = await session.post(
                    url.rstrip("/") + "/v1/converse/stream",
                    json=payload,
                    headers={"X-Destiny-Key": key},
                    timeout=aiohttp.ClientTimeout(total=None),
                )
                if resp.status != 200:
                    raise RuntimeError(f"status {resp.status}")
                chunks = resp.content.iter_any().__aiter__()
                while not pending:
                    pending = decoder.feed(await chunks.__anext__())
        except Exception as err:  # noqa: BLE001 - any start failure falls back
            _LOGGER.warning("Destiny stream could not start (%s); falling back", type(err).__name__)
            if resp is not None:
                resp.release()
            return await self._fallback(user_input, chat_log, url, key, payload)

        end: dict = {}

        async def _deltas() -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
            nonlocal end, pending
            yield {"role": "assistant"}
            events = pending
            try:
                while True:
                    for event in events:
                        if event["type"] == "delta" and isinstance(event.get("text"), str):
                            yield {"content": event["text"]}
                        elif event["type"] == "end":
                            end = event
                            return
                    try:
                        async with asyncio.timeout(IDLE_TIMEOUT):
                            chunk = await chunks.__anext__()
                    except StopAsyncIteration:
                        events = decoder.flush()
                        if not events:
                            break
                        continue
                    events = decoder.feed(chunk)
            except Exception as err:  # noqa: BLE001 - stall or broken connection
                _LOGGER.warning("Destiny stream interrupted (%s)", type(err).__name__)
            finally:
                resp.release()
            if not end:
                yield {"content": LOST_LINE}

        async for _ in chat_log.async_add_delta_content_stream(user_input.agent_id, _deltas()):
            pass

        if end:
            speech = end.get("speech", "")
            conv_id = end.get("conversation_id")
            cont = bool(end.get("continue_conversation", False))
        else:
            speech = LOST_LINE.strip()
            conv_id = payload.get("conversation_id")
            cont = False
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(speech)
        return conversation.ConversationResult(
            response=response,
            conversation_id=conv_id or chat_log.conversation_id,
            continue_conversation=cont,
        )

    async def _fallback(self, user_input, chat_log, url, key, payload):
        result = await self.hass.async_add_executor_job(brain_client.converse, url, key, payload)
        speech = result["speech"]
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=speech)
        )
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(speech)
        return conversation.ConversationResult(
            response=response,
            conversation_id=result.get("conversation_id") or chat_log.conversation_id,
            continue_conversation=bool(result.get("continue_conversation", False)),
        )
