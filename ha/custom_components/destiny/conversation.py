"""Destiny brain conversation entity."""
from __future__ import annotations

from typing import Literal

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import brain_client


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DestinyConversationEntity(entry)])


class DestinyConversationEntity(conversation.ConversationEntity):
    _attr_has_entity_name = False
    _attr_name = "Destiny brain"
    _attr_supports_streaming = False

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
        payload = {
            "text": user_input.text,
            "conversation_id": user_input.conversation_id,
            "device_id": user_input.device_id,
            "satellite_id": user_input.satellite_id,
            "language": user_input.language,
        }
        result = await self.hass.async_add_executor_job(
            brain_client.converse,
            self._entry.data["brain_url"],
            self._entry.data["shared_key"],
            payload,
        )
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
