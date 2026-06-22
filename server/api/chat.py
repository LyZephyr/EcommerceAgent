"""聊天 SSE 接口。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import cart_store
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from agent import AgentRecoveryExhausted, MessageCommitEvent, run_turn
from conversation import get_or_create_id
from schemas import ChatRequest
from sse.mapper import (
    GENERIC_ERROR_MESSAGE,
    RECOVERY_EXHAUSTED_MESSAGE,
    map_agent_event,
    map_done_event,
    map_error_event,
    product_card_from_data,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


async def iter_chat_sse_events(
    conversation_id: str,
    message: str,
    *,
    is_disconnected,
) -> AsyncIterator[dict[str, str]]:
    turn_events = run_turn(conversation_id, message)
    disconnected = False
    try:
        async for event in turn_events:
            if await is_disconnected():
                disconnected = True
                logger.info("chat_stream_disconnected conversation_id=%s", conversation_id)
                logger.info("llm_call_cancelled conversation_id=%s", conversation_id)
                await turn_events.aclose()
                return
            if isinstance(event, MessageCommitEvent):
                record_recent_products(conversation_id, event)
            mapped = map_agent_event(event, conversation_id=conversation_id)
            if mapped is not None:
                yield mapped
    except asyncio.CancelledError:
        disconnected = True
        logger.info("chat_stream_cancelled conversation_id=%s", conversation_id)
        logger.info("llm_call_cancelled conversation_id=%s", conversation_id)
        await turn_events.aclose()
        raise
    except AgentRecoveryExhausted as exc:
        logger.exception(
            "chat_agent_recovery_exhausted conversation_id=%s payload=%s",
            conversation_id,
            json.dumps(exc.to_payload(), ensure_ascii=False),
        )
        yield map_error_event(RECOVERY_EXHAUSTED_MESSAGE)
    except Exception:
        logger.exception("chat_stream_failed conversation_id=%s", conversation_id)
        yield map_error_event(GENERIC_ERROR_MESSAGE)
    finally:
        if not disconnected:
            yield map_done_event()


def record_recent_products(
    conversation_id: str,
    event: MessageCommitEvent,
) -> None:
    for entry in event.recent_products:
        card = product_card_from_data(entry.product_data, group=entry.group)
        cart_store.record_recent_product(
            conversation_id,
            card.model_dump(exclude_none=True),
        )


@router.post("/api/chat")
async def chat(chat_request: ChatRequest, http_request: Request):
    conv_id = get_or_create_id(chat_request.conversation_id)

    async def event_stream():
        async for sse_event in iter_chat_sse_events(
            conv_id,
            chat_request.message,
            is_disconnected=http_request.is_disconnected,
        ):
            yield sse_event

    return EventSourceResponse(event_stream())
