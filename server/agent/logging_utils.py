"""Agent 日志辅助函数。"""

from __future__ import annotations

import json
import time

from agent.constants import LOG_ARGUMENTS_MAX_CHARS


def elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000


def json_for_log(value, max_chars: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return truncate_for_log(text, max_chars)


def truncate_for_log(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...<truncated {len(text) - max_chars} chars>"


def log_tool_request(
    logger,
    tool_call_id: str,
    tool_name: str,
    arguments: dict,
) -> None:
    logger.info(
        "tool_call_request id=%s name=%s arguments=%s",
        tool_call_id,
        tool_name,
        json_for_log(arguments, LOG_ARGUMENTS_MAX_CHARS),
    )
