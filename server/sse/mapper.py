"""Agent 事件到 SSE 协议的映射。"""

from __future__ import annotations

import json
from typing import Any

import cart_store
from agent.events import (
    BlockCompareEvent,
    BlockProductEvent,
    BlockTextDeltaEvent,
    BlockTextEvent,
    CartEvent,
    MessageCommitEvent,
    MessageResetEvent,
    MessageStartEvent,
    StructuredStatusEvent,
)
from catalog.product_presenter import product_card_payload
from schemas import Product

AgentEvent = (
    CartEvent
    | BlockTextEvent
    | BlockTextDeltaEvent
    | BlockProductEvent
    | BlockCompareEvent
    | MessageStartEvent
    | MessageResetEvent
    | MessageCommitEvent
    | StructuredStatusEvent
)

RECOVERY_EXHAUSTED_MESSAGE = "模型输出连续异常，已停止本轮回复，请稍后重试。"
GENERIC_ERROR_MESSAGE = "服务处理失败，请稍后重试。"


def dump_sse_data(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def map_done_event() -> dict[str, str]:
    return {"event": "done", "data": "{}"}


def map_error_event(message: str) -> dict[str, str]:
    return {"event": "error", "data": dump_sse_data({"message": message})}


def map_message_start_event(event: MessageStartEvent) -> dict[str, str]:
    return {
        "event": "message_start",
        "data": dump_sse_data(
            {
                "message_id": event.message_id,
                "attempt_id": event.attempt_id,
                "provisional": event.provisional,
            }
        ),
    }


def map_message_reset_event(event: MessageResetEvent) -> dict[str, str]:
    return {
        "event": "message_reset",
        "data": dump_sse_data(
            {
                "message_id": event.message_id,
                "attempt_id": event.attempt_id,
                "reason": event.reason,
            }
        ),
    }


def map_message_commit_event(
    event: MessageCommitEvent,
    *,
    conversation_id: str,
) -> dict[str, str]:
    for entry in event.recent_products:
        card = product_card_from_data(
            entry["product_data"],
            group=entry.get("group"),
        )
        cart_store.record_recent_product(
            conversation_id,
            card.model_dump(exclude_none=True),
        )
    return {
        "event": "message_commit",
        "data": dump_sse_data(
            {
                "message_id": event.message_id,
                "attempt_id": event.attempt_id,
            }
        ),
    }


def map_cart_event(event: CartEvent) -> dict[str, str]:
    return {"event": "cart", "data": dump_sse_data(event.payload)}


def map_status_event(event: StructuredStatusEvent) -> dict[str, str]:
    return {
        "event": "status",
        "data": dump_sse_data(
            {
                "phase": event.phase,
                "message": event.message,
                "step": event.step,
                "total_steps": event.total_steps,
            }
        ),
    }


def map_block_text_event(event: BlockTextEvent) -> dict[str, str]:
    return {
        "event": "block",
        "data": dump_sse_data(
            {
                "type": "text",
                "message_id": event.message_id,
                "attempt_id": event.attempt_id,
                "block_id": event.block_id,
                "content": event.content,
            }
        ),
    }


def map_block_text_delta_event(event: BlockTextDeltaEvent) -> dict[str, str]:
    return {
        "event": "block",
        "data": dump_sse_data(
            {
                "type": "text_delta",
                "message_id": event.message_id,
                "attempt_id": event.attempt_id,
                "block_id": event.block_id,
                "content": event.content,
            }
        ),
    }


def map_block_compare_event(event: BlockCompareEvent) -> dict[str, str]:
    return {
        "event": "block",
        "data": dump_sse_data(
            {
                "type": "compare",
                "message_id": event.message_id,
                "attempt_id": event.attempt_id,
                "block_id": event.block_id,
                "compare": event.payload,
            }
        ),
    }


def product_card_from_data(product_data: dict, *, group: str | None = None) -> Product:
    card = Product(**product_card_payload(product_data, group_label=group))
    if group:
        card.group_label = group
    return card


def map_block_product_event(
    event: BlockProductEvent,
) -> dict[str, str]:
    card = product_card_from_data(event.product_data, group=event.group)
    payload: dict[str, Any] = {
        "type": "product",
        "message_id": event.message_id,
        "attempt_id": event.attempt_id,
        "block_id": event.block_id,
        "product": card.model_dump(exclude_none=True),
    }
    if event.group:
        payload["group"] = event.group
    return {"event": "block", "data": dump_sse_data(payload)}


def map_agent_event(
    event: AgentEvent,
    *,
    conversation_id: str,
) -> dict[str, str] | None:
    if isinstance(event, MessageStartEvent):
        return map_message_start_event(event)
    if isinstance(event, MessageResetEvent):
        return map_message_reset_event(event)
    if isinstance(event, MessageCommitEvent):
        return map_message_commit_event(event, conversation_id=conversation_id)
    if isinstance(event, CartEvent):
        return map_cart_event(event)
    if isinstance(event, BlockTextEvent):
        return map_block_text_event(event)
    if isinstance(event, BlockTextDeltaEvent):
        return map_block_text_delta_event(event)
    if isinstance(event, BlockProductEvent):
        return map_block_product_event(event)
    if isinstance(event, BlockCompareEvent):
        return map_block_compare_event(event)
    if isinstance(event, StructuredStatusEvent):
        return map_status_event(event)
    return None
