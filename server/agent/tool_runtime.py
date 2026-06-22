"""Tool-call parsing and execution for the Agent runtime."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import conversation
from agent.candidates import format_candidate_groups
from agent.constants import LOG_TOOL_RESULT_MAX_CHARS, MAX_TOOL_STEPS
from agent.contracts import (
    AgentState,
    CandidateProduct,
    ToolCall,
    candidate_groups_from_tool_result,
    flatten_candidate_group_products,
)
from agent.errors import RecoverableAgentError
from agent.events import CartEvent, StructuredStatusEvent
from agent.logging_utils import elapsed_ms, json_for_log, log_tool_request
from tools import execute as execute_tool

logger = logging.getLogger(__name__)

AgentEventEmitter = Callable[[Any], None]


async def execute_tool_calls(
    state: AgentState,
    *,
    emit: AgentEventEmitter,
) -> dict[str, Any]:
    budget = state["budget"].record_tool_step()
    messages = list(state["messages"])
    history_messages: list[dict[str, Any]] = []
    candidates_by_id = dict(state["candidates_by_id"])
    candidate_groups = list(state["candidate_groups"])
    used_retrieve_tool = state["used_retrieve_tool"]

    for index, tool_call in enumerate(state["pending_tool_calls"]):
        try:
            tool_name, arguments = parse_tool_arguments(tool_call)
            log_tool_request(logger, tool_call.id, tool_name, arguments)
            tool_start = time.perf_counter()

            if tool_name == "retrieve_products":
                emit(
                    StructuredStatusEvent(
                        phase="retrieving",
                        message="正在检索商品...",
                    )
                )
                current_candidate_groups = candidate_groups_from_tool_result(
                    execute_tool(tool_name, arguments)
                )
                used_retrieve_tool = True
                emit(
                    StructuredStatusEvent(
                        phase="filtering",
                        message="正在筛选库存和价格...",
                    )
                )
                _log_tool_result(tool_call, tool_name, tool_start, current_candidate_groups)
                candidate_groups.extend(current_candidate_groups)
                candidates_by_id.update(
                    {
                        product.product_id: product
                        for product in flatten_candidate_group_products(
                            current_candidate_groups
                        )
                    }
                )
                tool_content = format_candidate_groups(current_candidate_groups)
                history_content = tool_content
            elif is_cart_tool(tool_name):
                emit(
                    StructuredStatusEvent(
                        phase="cart",
                        message=cart_status(tool_name),
                    )
                )
                result = execute_tool(
                    tool_name,
                    arguments,
                    state["conversation_id"],
                )
                _log_tool_result(tool_call, tool_name, tool_start, result)
                if result.get("success") and result.get("cart"):
                    emit(CartEvent(result["cart"]))
                tool_content = json.dumps(result, ensure_ascii=False)
                history_content = tool_content
            else:
                result = execute_tool(tool_name, arguments)
                _log_tool_result(tool_call, tool_name, tool_start, result)
                tool_content = json.dumps(result, ensure_ascii=False)
                history_content = tool_content
        except RecoverableAgentError as exc:
            return recover_from_tool_error(state, messages, tool_call, index, exc, budget)
        except Exception as exc:
            return recover_from_tool_error(state, messages, tool_call, index, exc, budget)

        tool_message = {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": tool_content,
        }
        messages.append(tool_message)
        history_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": history_content,
            }
        )

    conversation.append(state["conversation_id"], state["messages"][-1])
    for history_message in history_messages:
        conversation.append(state["conversation_id"], history_message)
    state["recovery"].reset()
    next_tool_count = state["tool_step_count"] + 1
    if used_retrieve_tool:
        emit(
            StructuredStatusEvent(
                phase="composing",
                message="正在整理推荐...",
            )
        )
    return {
        "messages": messages,
        "candidates_by_id": candidates_by_id,
        "candidate_groups": candidate_groups,
        "used_retrieve_tool": used_retrieve_tool,
        "budget": budget,
        "tool_step_count": next_tool_count,
        "pending_tool_calls": [],
        "force_final": next_tool_count >= MAX_TOOL_STEPS,
        "route": "model",
    }


def parse_tool_arguments(tool_call: ToolCall | dict[str, Any]) -> tuple[str, dict[str, Any]]:
    call = tool_call if isinstance(tool_call, ToolCall) else ToolCall.from_mapping(tool_call)
    raw_arguments = call.arguments or "{}"
    try:
        arguments = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RecoverableAgentError(
            "tool_arguments_invalid",
            f"工具 {call.name} 的参数不是合法 JSON：{exc}",
            raw_output=raw_arguments,
            tool_name=call.name,
            tool_call_id=call.id,
            details={"exception_type": type(exc).__name__},
        ) from exc
    if not isinstance(arguments, dict):
        raise RecoverableAgentError(
            "tool_arguments_invalid",
            f"工具 {call.name} 的参数必须是 JSON object。",
            raw_output=raw_arguments,
            tool_name=call.name,
            tool_call_id=call.id,
            details={"actual_type": type(arguments).__name__},
        )
    return call.name, arguments


def recover_from_tool_error(
    state: AgentState,
    messages: list[dict[str, Any]],
    failed_tool_call: ToolCall,
    failed_index: int,
    exc: Exception,
    budget,
) -> dict[str, Any]:
    if isinstance(exc, RecoverableAgentError):
        error = exc
    else:
        error = RecoverableAgentError(
            "tool_execution_error",
            f"工具 {failed_tool_call.name} 执行失败：{exc}",
            raw_output=failed_tool_call.arguments,
            tool_name=failed_tool_call.name,
            tool_call_id=failed_tool_call.id,
            details={"exception_type": type(exc).__name__},
        )
    messages.append(
        {
            "role": "tool",
            "tool_call_id": failed_tool_call.id,
            "content": tool_error_content(error),
        }
    )
    for skipped in state["pending_tool_calls"][failed_index + 1 :]:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": skipped.id,
                "content": json.dumps(
                    {
                        "success": False,
                        "error_type": "tool_call_skipped",
                        "message": "前一个工具调用失败，本工具调用未执行。请重新生成整组工具调用。",
                        "tool_name": skipped.name,
                    },
                    ensure_ascii=False,
                ),
            }
        )
    feedback = state["recovery"].record(error, label="execute_tools")
    return {
        "messages": [*messages, {"role": "system", "content": feedback}],
        "budget": budget,
        "attempt_index": state["attempt_index"] + 1,
        "pending_tool_calls": [],
        "route": "model",
    }


def tool_error_content(error: RecoverableAgentError) -> str:
    return json.dumps(
        {
            "success": False,
            "error_type": error.error_type,
            "message": error.message,
            "tool_name": error.tool_name,
            "details": error.details,
        },
        ensure_ascii=False,
    )


def is_cart_tool(tool_name: str) -> bool:
    return tool_name in {
        "add_to_cart",
        "list_recent_products",
        "remove_from_cart",
        "update_cart_item",
        "view_cart",
        "clear_cart",
    }


def cart_status(tool_name: str) -> str:
    if tool_name == "list_recent_products":
        return "正在读取近期商品..."
    return "正在更新购物车..."


def _log_tool_result(
    tool_call: ToolCall,
    tool_name: str,
    tool_start: float,
    result: Any,
) -> None:
    logger.info(
        "tool_call_result id=%s name=%s duration_ms=%.2f result=%s",
        tool_call.id,
        tool_name,
        elapsed_ms(tool_start),
        json_for_log(_jsonable_result(result), LOG_TOOL_RESULT_MAX_CHARS),
    )


def _jsonable_result(result: Any) -> Any:
    if isinstance(result, list) and all(
        hasattr(item, "to_dict") for item in result
    ):
        return [item.to_dict() for item in result]
    if isinstance(result, CandidateProduct):
        return result.to_dict()
    return result
