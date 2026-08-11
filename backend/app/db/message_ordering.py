from __future__ import annotations

from typing import Any


def order_conversation_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order committed request pairs even when the database truncates timestamps."""

    turn_versions: dict[str, int] = {}
    for message in messages:
        message_id = str(message.get("message_id") or "")
        metadata = message.get("safe_metadata")
        if not message_id.startswith("msg_a_") or not isinstance(metadata, dict):
            continue
        state_version = metadata.get("state_version")
        if isinstance(state_version, int):
            turn_versions[message_id.removeprefix("msg_a_")] = state_version

    def sort_key(message: dict[str, Any]) -> tuple[int, int, str, str]:
        message_id = str(message.get("message_id") or "")
        request_digest = ""
        role_order = 2
        if message_id.startswith("msg_u_"):
            request_digest = message_id.removeprefix("msg_u_")
            role_order = 0
        elif message_id.startswith("msg_a_"):
            request_digest = message_id.removeprefix("msg_a_")
            role_order = 1
        state_version = turn_versions.get(request_digest)
        if state_version is not None:
            return (0, state_version, str(role_order), message_id)
        return (1, 0, str(message.get("created_at") or ""), message_id)

    return sorted(messages, key=sort_key)
