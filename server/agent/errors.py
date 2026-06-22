"""Agent 可恢复错误与重试状态。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from agent.constants import (
    LOG_ARGUMENTS_MAX_CHARS,
    LOG_LLM_OUTPUT_MAX_CHARS,
    MAX_RECOVERY_RETRIES,
    MAX_TOTAL_RECOVERY_ATTEMPTS,
)
from agent.logging_utils import json_for_log, truncate_for_log

logger = logging.getLogger(__name__)


class RecoverableAgentError(RuntimeError):
    """可反馈给 LLM 修正的边界错误。"""

    def __init__(
        self,
        error_type: str,
        message: str,
        *,
        raw_output: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.raw_output = raw_output
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self.details = details or {}

    @property
    def retry_key(self) -> str:
        if self.tool_name:
            return f"{self.error_type}:{self.tool_name}"
        return self.error_type

    def to_feedback(self, *, retry_count: int) -> str:
        payload = {
            "error_type": self.error_type,
            "message": self.message,
            "retry_count": retry_count,
            "max_retries": MAX_RECOVERY_RETRIES,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "details": self.details,
            "raw_output": truncate_for_log(self.raw_output or "", LOG_LLM_OUTPUT_MAX_CHARS)
            if self.raw_output
            else None,
        }
        return (
            "上一轮输出无法被系统消费，请只修正导致失败的部分并重新回答。\n"
            "错误信息如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
            "要求：\n"
            "- 如果是工具调用错误，请重新生成合法的工具名和 JSON 参数。\n"
            "- 如果你决定推荐候选商品，请严格使用 "
            '<R><INTRO>短建议<ITEM id="商品ID">短理由<OUTRO>可选短总结；'
            "如果候选为空或不符合需求，不要输出 <R>。\n"
            "- 如果是对比标记错误，请严格使用 "
            '<C>{"products":[...],"rows":[...]}</C>，且二者不能同时出现。\n'
            "- 推荐场景 <R> 前不要写任何非空正文，推荐块不要写任何闭合标签；非推荐场景不要输出 <R>。\n"
            "- 不要解释修正过程。"
        )


class AgentRecoveryExhausted(RuntimeError):
    def __init__(self, error: RecoverableAgentError, retry_count: int) -> None:
        super().__init__(
            f"Agent 连续 {retry_count} 次遇到同类可恢复错误后停止："
            f"{error.error_type} - {error.message}"
        )
        self.error = error
        self.retry_count = retry_count

    def to_payload(self) -> dict:
        return {
            "error_type": self.error.error_type,
            "message": self.error.message,
            "attempts": self.retry_count,
            "tool_name": self.error.tool_name,
            "tool_call_id": self.error.tool_call_id,
            "details": self.error.details,
            "recoverable": False,
        }


@dataclass
class RecoveryState:
    retry_key: str | None = None
    retry_count: int = 0
    total_count: int = 0

    def record(self, error: RecoverableAgentError, *, label: str) -> str:
        self.total_count += 1
        if error.retry_key == self.retry_key:
            self.retry_count += 1
        else:
            self.retry_key = error.retry_key
            self.retry_count = 1

        if (
            self.retry_count > MAX_RECOVERY_RETRIES
            or self.total_count > MAX_TOTAL_RECOVERY_ATTEMPTS
        ):
            logger.error(
                "agent_recovery_exhausted label=%s error_type=%s retry_key=%s "
                "retry_count=%s total_count=%s details=%s raw_output=%s",
                label,
                error.error_type,
                error.retry_key,
                self.retry_count,
                self.total_count,
                json_for_log(error.details, LOG_ARGUMENTS_MAX_CHARS),
                truncate_for_log(error.raw_output or "", LOG_LLM_OUTPUT_MAX_CHARS),
            )
            raise AgentRecoveryExhausted(error, self.retry_count) from error

        logger.warning(
            "agent_recoverable_error label=%s error_type=%s retry_key=%s "
            "retry_count=%s total_count=%s message=%s details=%s raw_output=%s",
            label,
            error.error_type,
            error.retry_key,
            self.retry_count,
            self.total_count,
            error.message,
            json_for_log(error.details, LOG_ARGUMENTS_MAX_CHARS),
            truncate_for_log(error.raw_output or "", LOG_LLM_OUTPUT_MAX_CHARS),
        )
        return error.to_feedback(retry_count=self.retry_count)

    def reset(self) -> None:
        self.retry_key = None
        self.retry_count = 0
        self.total_count = 0
