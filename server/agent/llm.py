"""LLM 调用与流式最终回复。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

import conversation
from agent.constants import LLM_TIMEOUT_SECONDS
from agent.emitters import append_final_response, events_from_parsed_response
from agent.errors import RecoverableAgentError, RecoveryState
from agent.events import (
    BlockCompareEvent,
    BlockProductEvent,
    BlockTextDeltaEvent,
    BlockTextEvent,
    StructuredStatusEvent,
)
from agent.logging_utils import elapsed_ms
from agent.streaming import StreamingFinalEmitter
from config import ARK_MODEL

logger = logging.getLogger(__name__)


async def create_chat_completion(
    client: AsyncOpenAI,
    *,
    label: str,
    **kwargs,
):
    start = time.perf_counter()
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=LLM_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        logger.info(
            "llm_call_cancelled label=%s model=%s duration_ms=%.2f",
            label,
            kwargs.get("model"),
            elapsed_ms(start),
        )
        raise
    except TimeoutError as exc:
        elapsed = elapsed_ms(start)
        logger.warning(
            "llm_call_timeout label=%s model=%s duration_ms=%.2f timeout_seconds=%s",
            label,
            kwargs.get("model"),
            elapsed,
            LLM_TIMEOUT_SECONDS,
        )
        raise RecoverableAgentError(
            "llm_timeout",
            f"LLM 调用超过 {LLM_TIMEOUT_SECONDS} 秒无响应。",
            details={
                "label": label,
                "model": kwargs.get("model"),
                "timeout_seconds": LLM_TIMEOUT_SECONDS,
                "duration_ms": elapsed,
            },
        ) from exc
    except Exception as exc:
        elapsed = elapsed_ms(start)
        logger.exception(
            "llm_call_error label=%s model=%s duration_ms=%.2f",
            label,
            kwargs.get("model"),
            elapsed,
        )
        raise RecoverableAgentError(
            "llm_call_error",
            f"LLM 调用失败：{exc}",
            details={
                "label": label,
                "model": kwargs.get("model"),
                "duration_ms": elapsed,
                "exception_type": type(exc).__name__,
            },
        ) from exc
    elapsed = elapsed_ms(start)
    finish_reason = response.choices[0].finish_reason if response.choices else None
    logger.info(
        "llm_call label=%s model=%s duration_ms=%.2f finish_reason=%s",
        label,
        kwargs.get("model"),
        elapsed,
        finish_reason,
    )
    return response


async def stream_final_response_with_recovery(
    client: AsyncOpenAI,
    *,
    conversation_id: str,
    messages: list[dict],
    candidates_by_id: dict[str, dict],
    candidate_groups: list[dict],
    require_recommend_marker: bool,
    message_id: str,
    recovery: RecoveryState,
    label: str,
) -> AsyncIterator[
    BlockTextEvent
    | BlockTextDeltaEvent
    | BlockProductEvent
    | BlockCompareEvent
    | StructuredStatusEvent
]:
    while True:
        try:
            async for event in stream_final_response(
                client,
                conversation_id=conversation_id,
                messages=messages,
                candidates_by_id=candidates_by_id,
                candidate_groups=candidate_groups,
                require_recommend_marker=require_recommend_marker,
                message_id=message_id,
                label=label,
            ):
                yield event
            return
        except RecoverableAgentError as exc:
            feedback = recovery.record(exc, label=label)
            messages.append({"role": "system", "content": feedback})


async def stream_final_response(
    client: AsyncOpenAI,
    *,
    conversation_id: str,
    messages: list[dict],
    candidates_by_id: dict[str, dict],
    candidate_groups: list[dict],
    require_recommend_marker: bool,
    message_id: str,
    label: str,
) -> AsyncIterator[
    BlockTextEvent
    | BlockTextDeltaEvent
    | BlockProductEvent
    | BlockCompareEvent
    |     StructuredStatusEvent
]:
    yield StructuredStatusEvent(
        phase="streaming",
        message="正在输出推荐..." if require_recommend_marker else "正在输出回复...",
        step=4 if require_recommend_marker else None,
        total_steps=4 if require_recommend_marker else None,
    )
    emitter = StreamingFinalEmitter(
        message_id=message_id,
        candidates_by_id=candidates_by_id,
        candidate_groups=candidate_groups,
        require_recommend_marker=require_recommend_marker,
    )
    start = time.perf_counter()
    first_chunk_ms: float | None = None
    completed = False
    chunk_count = 0
    stream = None
    try:
        stream = await asyncio.wait_for(
            client.chat.completions.create(
                model=ARK_MODEL,
                messages=messages,
                temperature=0.3,
                stream=True,
            ),
            timeout=LLM_TIMEOUT_SECONDS,
        )
        async for chunk in stream:
            chunk_count += 1
            if first_chunk_ms is None:
                first_chunk_ms = elapsed_ms(start)
            delta = chunk.choices[0].delta if chunk.choices else None
            text_delta = getattr(delta, "content", None) if delta is not None else None
            if not text_delta:
                continue
            for event in emitter.feed(text_delta):
                yield event
        parsed_response = emitter.finish()
        if parsed_response.compare_payload:
            async for event in events_from_parsed_response(
                parsed_response,
                candidates_by_id,
                message_id=message_id,
            ):
                yield event
        append_final_response(
            conversation,
            conversation_id,
            parsed_response,
            candidates_by_id,
        )
        completed = True
        logger.info(
            "llm_stream_call label=%s model=%s duration_ms=%.2f first_chunk_ms=%s "
            "first_visible_ms=%s chunks=%s visible_chars=%s",
            label,
            ARK_MODEL,
            elapsed_ms(start),
            f"{first_chunk_ms:.2f}" if first_chunk_ms is not None else None,
            (
                f"{emitter.first_visible_ms:.2f}"
                if emitter.first_visible_ms is not None
                else None
            ),
            chunk_count,
            emitter.visible_char_count,
        )
    except asyncio.CancelledError:
        logger.info(
            "llm_call_cancelled label=%s model=%s duration_ms=%.2f chunks=%s",
            label,
            ARK_MODEL,
            elapsed_ms(start),
            chunk_count,
        )
        raise
    except TimeoutError as exc:
        raise RecoverableAgentError(
            "llm_timeout",
            f"LLM streaming 调用超过 {LLM_TIMEOUT_SECONDS} 秒无响应。",
            details={
                "label": label,
                "model": ARK_MODEL,
                "timeout_seconds": LLM_TIMEOUT_SECONDS,
                "duration_ms": elapsed_ms(start),
            },
        ) from exc
    except RecoverableAgentError:
        raise
    except Exception as exc:
        logger.exception(
            "llm_stream_call_error label=%s model=%s duration_ms=%.2f",
            label,
            ARK_MODEL,
            elapsed_ms(start),
        )
        raise RecoverableAgentError(
            "llm_call_error",
            f"LLM streaming 调用失败：{exc}",
            details={
                "label": label,
                "model": ARK_MODEL,
                "duration_ms": elapsed_ms(start),
                "exception_type": type(exc).__name__,
            },
        ) from exc
    finally:
        if not completed and emitter.has_visible_output:
            conversation.append(
                conversation_id,
                {
                    "role": "assistant",
                    "content": emitter.interrupted_history_text(candidates_by_id),
                },
            )
        if stream is not None and hasattr(stream, "aclose"):
            with contextlib.suppress(Exception):
                await stream.aclose()
