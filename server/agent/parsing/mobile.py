"""移动端可见回复校验。"""

from __future__ import annotations

from agent.constants import (
    MOBILE_VISIBLE_REPLY_MAX_CHARS,
    VISIBLE_MARKDOWN_TOKEN_RE,
)
from agent.errors import RecoverableAgentError


def validate_mobile_visible_reply(
    visible_text: str,
    *,
    raw_output: str,
    enforce_length: bool,
    max_chars: int = MOBILE_VISIBLE_REPLY_MAX_CHARS,
    field_name: str = "visible_reply",
) -> None:
    stripped_text = visible_text.strip()
    markdown_match = VISIBLE_MARKDOWN_TOKEN_RE.search(stripped_text)
    if markdown_match:
        raise RecoverableAgentError(
            "visible_reply_markdown",
            "用户可见回复不能包含 Markdown 标题、加粗、表格或分隔线语法。",
            raw_output=raw_output,
            details={"token": markdown_match.group(0)},
        )
    if enforce_length and len(stripped_text) > max_chars:
        raise RecoverableAgentError(
            "visible_reply_too_long",
            f"{field_name} 不能超过 {max_chars} 个字符。",
            raw_output=raw_output,
            details={
                "field_name": field_name,
                "max_chars": max_chars,
                "actual_chars": len(stripped_text),
            },
        )
