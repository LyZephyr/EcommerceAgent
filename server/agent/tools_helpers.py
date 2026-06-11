"""工具调用解析与辅助。"""

from __future__ import annotations

import json
import logging
import traceback

from agent.constants import LOG_TOOL_RESULT_MAX_CHARS
from agent.errors import RecoverableAgentError
from agent.logging_utils import elapsed_ms, json_for_log

logger = logging.getLogger(__name__)


def parse_tool_call(tool_call) -> tuple[str, dict]:
    tool_name = tool_call.function.name
    raw_arguments = tool_call.function.arguments or "{}"
    try:
        arguments = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RecoverableAgentError(
            "tool_arguments_invalid",
            f"工具 {tool_name} 的参数不是合法 JSON：{exc}",
            raw_output=raw_arguments,
            tool_name=tool_name,
            tool_call_id=tool_call.id,
            details={"exception_type": type(exc).__name__},
        ) from exc
    if not isinstance(arguments, dict):
        raise RecoverableAgentError(
            "tool_arguments_invalid",
            f"工具 {tool_name} 的参数必须是 JSON object。",
            raw_output=raw_arguments,
            tool_name=tool_name,
            tool_call_id=tool_call.id,
            details={"actual_type": type(arguments).__name__},
        )
    return tool_name, arguments


def log_tool_result(
    tool_call_id: str,
    tool_name: str,
    result,
    started_at: float,
) -> None:
    logger.info(
        "tool_call_result id=%s name=%s duration_ms=%.2f result=%s",
        tool_call_id,
        tool_name,
        elapsed_ms(started_at),
        json_for_log(result, LOG_TOOL_RESULT_MAX_CHARS),
    )


def tool_call_message(tool_calls) -> dict:
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in tool_calls
        ],
    }


def is_cart_tool(tool_name: str) -> bool:
    return tool_name in {
        "add_to_cart",
        "list_recent_products",
        "remove_from_cart",
        "update_cart_item",
        "view_cart",
        "clear_cart",
    }


def is_retrieve_tool(tool_name: str) -> bool:
    return tool_name == "retrieve_products"


def cart_status(tool_name: str) -> str:
    if tool_name == "list_recent_products":
        return "正在读取近期商品..."
    return "正在更新购物车..."


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


def append_skipped_tool_errors(
    messages: list[dict],
    tool_calls,
    *,
    after_tool_call_id: str,
) -> None:
    should_skip = False
    for tool_call in tool_calls:
        if tool_call.id == after_tool_call_id:
            should_skip = True
            continue
        if not should_skip:
            continue
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(
                    {
                        "success": False,
                        "error_type": "tool_call_skipped",
                        "message": "前一个工具调用失败，本工具调用未执行。请重新生成整组工具调用。",
                        "tool_name": tool_call.function.name,
                    },
                    ensure_ascii=False,
                ),
            }
        )


def recoverable_tool_execution_error(tool_call, exc: Exception) -> RecoverableAgentError:
    return RecoverableAgentError(
        "tool_execution_error",
        f"工具 {tool_call.function.name} 执行失败：{exc}",
        raw_output=tool_call.function.arguments or "",
        tool_name=tool_call.function.name,
        tool_call_id=tool_call.id,
        details={
            "exception_type": type(exc).__name__,
            "traceback": "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
        },
    )


def assistant_message_or_raise(response):
    if not response.choices:
        raise RecoverableAgentError(
            "llm_empty_response",
            "LLM 响应中没有 choices。",
            details={"response": str(response)},
        )
    message = response.choices[0].message
    if message is None:
        raise RecoverableAgentError(
            "llm_empty_response",
            "LLM 响应中没有 assistant message。",
            details={"finish_reason": response.choices[0].finish_reason},
        )
    return message
