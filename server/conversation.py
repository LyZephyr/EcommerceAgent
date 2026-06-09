"""会话历史管理：维护多轮对话上下文。"""

from __future__ import annotations

import uuid

_MAX_ROUNDS = 10

_conversations: dict[str, list[dict]] = {}


def get_or_create_id(conversation_id: str | None) -> str:
    if conversation_id and conversation_id in _conversations:
        return conversation_id
    new_id = conversation_id or uuid.uuid4().hex
    _conversations[new_id] = []
    return new_id


def get_history(conversation_id: str) -> list[dict]:
    return list(_conversations.get(conversation_id, []))


def append(conversation_id: str, message: dict) -> None:
    history = _conversations.setdefault(conversation_id, [])
    history.append(message)
    _trim(history)


def _trim(history: list[dict]) -> None:
    """保留最近 _MAX_ROUNDS 轮对话。以 user 消息计数轮次。"""
    user_indices = [i for i, m in enumerate(history) if m.get("role") == "user"]
    if len(user_indices) > _MAX_ROUNDS:
        cut = user_indices[-_MAX_ROUNDS]
        del history[:cut]
