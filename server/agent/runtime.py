"""Model runtime and transition logic for a single Agent turn."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

import conversation
from openai import AsyncOpenAI

from agent.contracts import (
    AgentState,
    CandidateProduct,
    RecentProductEntry,
    ToolCall,
    candidate_groups_to_dicts,
    candidates_to_dicts,
)
from agent.emitters import append_final_response, events_from_parsed_response
from agent.errors import AgentRecoveryExhausted, RecoverableAgentError
from agent.events import (
    MessageCommitEvent,
    MessageResetEvent,
    MessageStartEvent,
    StructuredStatusEvent,
)
from agent.logging_utils import elapsed_ms
from agent.streaming import StreamingFinalEmitter
from agent.tool_runtime import execute_tool_calls
from agent.constants import LLM_TIMEOUT_SECONDS
from config import ARK_API_KEY, ARK_BASE_URL, ARK_MODEL
from tools import TOOL_DEFINITIONS

logger = logging.getLogger(__name__)
_EVENT_EMITTER: ContextVar[Callable[[Any], None] | None] = ContextVar(
    "agent_event_emitter",
    default=None,
)


async def model_step(state: AgentState) -> dict[str, Any]:
    budget = state["budget"].record_model_step(force_final=state.get("force_final", False))
    label = model_label(state)
    start = time.perf_counter()
    visible_started = False
    tool_started = False
    reset_for_tool = False
    chunk_count = 0
    first_chunk_ms: float | None = None
    attempt_id = attempt_id_for(state)
    candidates_by_id = candidates_to_dicts(state["candidates_by_id"])
    candidate_groups = candidate_groups_to_dicts(state["candidate_groups"])
    emitter = StreamingFinalEmitter(
        message_id=state["message_id"],
        attempt_id=attempt_id,
        candidates_by_id=candidates_by_id,
        candidate_groups=candidate_groups,
    )
    stream = None
    tool_calls: dict[int, dict[str, Any]] = {}

    try:
        async with asyncio.timeout(LLM_TIMEOUT_SECONDS):
            stream = await create_stream(state, label=label)
            async for chunk in stream:
                chunk_count += 1
                if first_chunk_ms is None:
                    first_chunk_ms = elapsed_ms(start)
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                if getattr(delta, "tool_calls", None):
                    if visible_started and not reset_for_tool:
                        writer_emit(
                            MessageResetEvent(
                                message_id=state["message_id"],
                                attempt_id=attempt_id,
                                reason="tool_call_after_text",
                            )
                        )
                        reset_for_tool = True
                    tool_started = True
                    merge_tool_call_chunks(tool_calls, delta.tool_calls)
                    continue

                text_delta = getattr(delta, "content", None)
                if not text_delta or tool_started:
                    continue
                if not visible_started:
                    visible_started = True
                    writer_emit(MessageStartEvent(state["message_id"], attempt_id))
                    writer_emit(
                        StructuredStatusEvent(
                            phase="streaming",
                            message="正在输出回复...",
                        )
                    )
                for event in emitter.feed(text_delta):
                    writer_emit(event)

        built_tool_calls = built_tool_calls_from_chunks(tool_calls)
        if built_tool_calls:
            if state.get("force_final"):
                raise AgentRecoveryExhausted(
                    RecoverableAgentError(
                        "force_final_tool_call",
                        "force-final model call still produced tool calls.",
                        details={"tool_names": [call.name for call in built_tool_calls]},
                    ),
                    budget.transitions,
                )
            assistant_message = {
                "role": "assistant",
                "tool_calls": [call.to_openai_dict() for call in built_tool_calls],
            }
            return {
                "messages": [*state["messages"], assistant_message],
                "budget": budget,
                "pending_tool_calls": built_tool_calls,
                "attempt_index": state["attempt_index"] + 1
                if reset_for_tool
                else state["attempt_index"],
                "route": "tools",
            }

        if not visible_started:
            raise RecoverableAgentError(
                "llm_empty_response",
                "LLM streaming 响应没有可见文本或工具调用。",
                details={"label": label, "model": ARK_MODEL},
            )

        parsed_response = emitter.finish()
        if parsed_response.compare_payload:
            async for event in events_from_parsed_response(
                parsed_response,
                candidates_by_id,
                message_id=state["message_id"],
                attempt_id=attempt_id,
            ):
                writer_emit(event)
        writer_emit(
            MessageCommitEvent(
                message_id=state["message_id"],
                attempt_id=attempt_id,
                recent_products=recent_products_from_parsed_response(
                    parsed_response,
                    state["candidates_by_id"],
                ),
            )
        )
        append_final_response(
            conversation,
            state["conversation_id"],
            parsed_response,
            candidates_by_id,
        )
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
        return {"budget": budget, "route": "done", "pending_tool_calls": []}
    except asyncio.CancelledError:
        logger.info(
            "llm_call_cancelled label=%s model=%s duration_ms=%.2f chunks=%s",
            label,
            ARK_MODEL,
            elapsed_ms(start),
            chunk_count,
        )
        raise
    except TimeoutError:
        return recover_from_model_error(
            state,
            RecoverableAgentError(
                "llm_timeout",
                f"LLM streaming 调用超过 {LLM_TIMEOUT_SECONDS} 秒无响应。",
                details={
                    "label": label,
                    "model": ARK_MODEL,
                    "timeout_seconds": LLM_TIMEOUT_SECONDS,
                    "duration_ms": elapsed_ms(start),
                },
            ),
            visible_started=visible_started,
            attempt_id=attempt_id,
            budget=budget,
        )
    except AgentRecoveryExhausted:
        raise
    except RecoverableAgentError as exc:
        return recover_from_model_error(
            state,
            exc,
            visible_started=visible_started,
            attempt_id=attempt_id,
            budget=budget,
        )
    except Exception as exc:
        logger.exception(
            "llm_stream_call_error label=%s model=%s duration_ms=%.2f",
            label,
            ARK_MODEL,
            elapsed_ms(start),
        )
        return recover_from_model_error(
            state,
            RecoverableAgentError(
                "llm_call_error",
                f"LLM streaming 调用失败：{exc}",
                details={
                    "label": label,
                    "model": ARK_MODEL,
                    "duration_ms": elapsed_ms(start),
                    "exception_type": type(exc).__name__,
                },
            ),
            visible_started=visible_started,
            attempt_id=attempt_id,
            budget=budget,
        )
    finally:
        if stream is not None and hasattr(stream, "aclose"):
            await stream.aclose()


async def tool_step(state: AgentState) -> dict[str, Any]:
    return await execute_tool_calls(state, emit=writer_emit)


async def create_stream(state: AgentState, *, label: str):
    kwargs: dict[str, Any] = {
        "model": ARK_MODEL,
        "messages": messages_for_model(state),
        "temperature": 0.3,
        "stream": True,
    }
    if not state.get("force_final"):
        kwargs["tools"] = TOOL_DEFINITIONS
    client = AsyncOpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)
    return await client.chat.completions.create(**kwargs)


def messages_for_model(state: AgentState) -> list[dict[str, Any]]:
    if not state.get("force_final"):
        return state["messages"]
    return [
        *state["messages"],
        {
            "role": "system",
            "content": "工具调用次数已达上限，请基于已有工具结果直接回复用户；如果信息仍不足，请追问用户。",
        },
    ]


def recover_from_model_error(
    state: AgentState,
    error: RecoverableAgentError,
    *,
    visible_started: bool,
    attempt_id: str,
    budget,
) -> dict[str, Any]:
    if visible_started:
        writer_emit(
            MessageResetEvent(
                message_id=state["message_id"],
                attempt_id=attempt_id,
                reason="retry",
            )
        )
    feedback = state["recovery"].record(error, label=model_label(state))
    return {
        "messages": [*state["messages"], {"role": "system", "content": feedback}],
        "budget": budget,
        "attempt_index": state["attempt_index"] + 1,
        "pending_tool_calls": [],
        "route": "model",
    }


def model_label(state: AgentState) -> str:
    if state.get("force_final"):
        return "final_after_tool_limit"
    return f"model_step_{state.get('tool_step_count', 0) + 1}"


def attempt_id_for(state: AgentState) -> str:
    return f"attempt-{state['attempt_index']}"


def merge_tool_call_chunks(tool_calls: dict[int, dict[str, Any]], chunks) -> None:
    for chunk in chunks:
        index = getattr(chunk, "index", None)
        if index is None:
            continue
        tool_call = tool_calls.setdefault(
            index,
            {
                "id": None,
                "type": "function",
                "function": {"name": None, "arguments": ""},
            },
        )
        call_id = getattr(chunk, "id", None)
        if call_id:
            tool_call["id"] = call_id
        call_type = getattr(chunk, "type", None)
        if call_type:
            tool_call["type"] = call_type
        function = getattr(chunk, "function", None)
        if function is None:
            continue
        name = getattr(function, "name", None)
        if name:
            tool_call["function"]["name"] = name
        arguments = getattr(function, "arguments", None)
        if arguments:
            tool_call["function"]["arguments"] += arguments


def built_tool_calls_from_chunks(tool_calls: dict[int, dict[str, Any]]) -> list[ToolCall]:
    built: list[ToolCall] = []
    for index in sorted(tool_calls):
        tool_call = tool_calls[index]
        tool_call["id"] = tool_call["id"] or f"call_{uuid4().hex}"
        call = ToolCall.from_mapping(tool_call)
        if not call.name:
            raise RecoverableAgentError(
                "tool_call_invalid",
                "LLM 生成了缺少工具名的工具调用。",
                details={"tool_call": tool_call},
            )
        built.append(call)
    return built


def recent_products_from_parsed_response(
    parsed_response,
    candidates_by_id: dict[str, CandidateProduct],
) -> list[RecentProductEntry]:
    if not parsed_response.recommendation:
        return []
    products = []
    for item in parsed_response.recommendation.items:
        product = candidates_by_id.get(item.product_id)
        if product:
            products.append(
                RecentProductEntry(product_data=product.to_dict(), group=item.group)
            )
    return products


def writer_emit(event) -> None:
    emitter = _EVENT_EMITTER.get()
    if emitter is not None:
        emitter(event)
        return
    logger.warning(
        "writer_emit called without event emitter set, event dropped: %s",
        type(event).__name__,
    )


@contextmanager
def use_event_emitter(emit: Callable[[Any], None]) -> Iterator[None]:
    token = _EVENT_EMITTER.set(emit)
    try:
        yield
    finally:
        _EVENT_EMITTER.reset(token)
