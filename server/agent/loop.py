"""Agent ReAct 主循环。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from uuid import uuid4

from openai import AsyncOpenAI

import conversation
from agent.candidates import flatten_candidate_groups, format_candidate_groups
from agent.constants import MAX_TOOL_STEPS
from agent.events import (
    BlockCompareEvent,
    BlockProductEvent,
    BlockTextDeltaEvent,
    BlockTextEvent,
    CartEvent,
    StructuredStatusEvent,
)
from agent.errors import RecoverableAgentError, RecoveryState
from agent.llm import (
    create_chat_completion,
    stream_final_response_with_recovery,
)
from agent.logging_utils import log_tool_request
from agent.prompts import SYSTEM_PROMPT
from agent.tools_helpers import (
    append_skipped_tool_errors,
    assistant_message_or_raise,
    cart_status,
    is_cart_tool,
    is_retrieve_tool,
    log_tool_result,
    parse_tool_call,
    recoverable_tool_execution_error,
    tool_call_message,
    tool_error_content,
)
from config import ARK_API_KEY, ARK_BASE_URL, ARK_MODEL
from tools import TOOL_DEFINITIONS, execute as execute_tool

logger = logging.getLogger(__name__)


async def run_turn(
    conversation_id: str,
    user_message: str,
) -> AsyncIterator[
    CartEvent
    | BlockTextEvent
    | BlockTextDeltaEvent
    | BlockProductEvent
    | BlockCompareEvent
    | StructuredStatusEvent
]:
    """执行一轮对话，yield block/cart/status 事件。"""
    if not ARK_API_KEY:
        raise RuntimeError(
            "缺少 ARK_API_KEY，请在项目根目录 .env 中配置正确的 API Key。"
        )

    conversation.append(conversation_id, {"role": "user", "content": user_message})
    history = conversation.get_history(conversation_id)

    client = AsyncOpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ] + history
    candidates_by_id: dict[str, dict] = {}
    candidate_groups: list[dict] = []
    recovery = RecoveryState()
    used_retrieve_tool = False
    message_id = f"asst-{uuid4().hex}"

    step_index = 0
    while step_index < MAX_TOOL_STEPS:
        label = f"react_step_{step_index + 1}"
        try:
            response = await create_chat_completion(
                client,
                label=label,
                model=ARK_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                temperature=0.3,
            )
            assistant_msg = assistant_message_or_raise(response)

            if not assistant_msg.tool_calls:
                if used_retrieve_tool:
                    yield StructuredStatusEvent(
                        phase="composing",
                        message="正在整理推荐...",
                        step=3,
                        total_steps=4,
                    )
                async for event in stream_final_response_with_recovery(
                    client,
                    conversation_id=conversation_id,
                    messages=messages,
                    candidates_by_id=candidates_by_id,
                    candidate_groups=candidate_groups,
                    message_id=message_id,
                    recovery=recovery,
                    label="final_stream",
                ):
                    yield event
                return

            tool_call_msg = tool_call_message(assistant_msg.tool_calls)
            messages.append(tool_call_msg)
            tool_history_messages = []
            tool_failed = False

            for tool_call in assistant_msg.tool_calls:
                try:
                    tool_name, arguments = parse_tool_call(tool_call)
                    log_tool_request(logger, tool_call.id, tool_name, arguments)
                    tool_start = time.perf_counter()

                    if is_retrieve_tool(tool_name):
                        yield StructuredStatusEvent(
                            phase="retrieving",
                            message="正在检索商品...",
                            step=1,
                            total_steps=4,
                        )
                        try:
                            current_candidate_groups = execute_tool(tool_name, arguments)
                        except Exception as exc:
                            raise recoverable_tool_execution_error(
                                tool_call,
                                exc,
                            ) from exc
                        used_retrieve_tool = True
                        yield StructuredStatusEvent(
                            phase="filtering",
                            message="正在筛选库存和价格...",
                            step=2,
                            total_steps=4,
                        )
                        log_tool_result(
                            tool_call.id,
                            tool_name,
                            current_candidate_groups,
                            tool_start,
                        )
                        candidate_groups.extend(current_candidate_groups)
                        candidates_by_id.update(
                            {
                                product["product_id"]: product
                                for product in flatten_candidate_groups(
                                    current_candidate_groups
                                )
                            }
                        )
                        tool_content = format_candidate_groups(current_candidate_groups)
                        history_content = tool_content
                    elif is_cart_tool(tool_name):
                        yield StructuredStatusEvent(
                            phase="cart",
                            message=cart_status(tool_name),
                        )
                        try:
                            result = execute_tool(tool_name, arguments, conversation_id)
                        except Exception as exc:
                            raise recoverable_tool_execution_error(
                                tool_call,
                                exc,
                            ) from exc
                        log_tool_result(tool_call.id, tool_name, result, tool_start)
                        if result.get("success") and result.get("cart"):
                            yield CartEvent(result["cart"])
                        tool_content = json.dumps(result, ensure_ascii=False)
                        history_content = tool_content
                    else:
                        try:
                            result = execute_tool(tool_name, arguments)
                        except Exception as exc:
                            raise recoverable_tool_execution_error(
                                tool_call,
                                exc,
                            ) from exc
                        log_tool_result(tool_call.id, tool_name, result, tool_start)
                        tool_content = json.dumps(result, ensure_ascii=False)
                        history_content = tool_content
                except RecoverableAgentError as exc:
                    tool_failed = True
                    tool_content = tool_error_content(exc)
                    feedback = recovery.record(exc, label=label)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_content,
                        }
                    )
                    append_skipped_tool_errors(
                        messages,
                        assistant_msg.tool_calls,
                        after_tool_call_id=tool_call.id,
                    )
                    messages.append({"role": "system", "content": feedback})
                    break

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_content,
                }
                messages.append(tool_msg)
                tool_history_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": history_content,
                    }
                )

            if tool_failed:
                continue

            conversation.append(conversation_id, tool_call_msg)
            for history_message in tool_history_messages:
                conversation.append(conversation_id, history_message)
            recovery.reset()
            step_index += 1
        except RecoverableAgentError as exc:
            feedback = recovery.record(exc, label=label)
            messages.append({"role": "system", "content": feedback})
            continue

    while True:
        label = "final_after_tool_limit"
        try:
            if used_retrieve_tool:
                yield StructuredStatusEvent(
                    phase="composing",
                    message="正在整理推荐...",
                    step=3,
                    total_steps=4,
                )
            async for event in stream_final_response_with_recovery(
                client,
                conversation_id=conversation_id,
                messages=messages
                + [
                    {
                        "role": "system",
                        "content": "工具调用次数已达上限，请基于已有工具结果直接回复用户；如果信息仍不足，请追问用户。",
                    }
                ],
                candidates_by_id=candidates_by_id,
                candidate_groups=candidate_groups,
                message_id=message_id,
                recovery=recovery,
                label=label,
            ):
                yield event
            return
        except RecoverableAgentError as exc:
            feedback = recovery.record(exc, label=label)
            messages.append({"role": "system", "content": feedback})
