"""隐藏事件标记语法校验。"""

from __future__ import annotations

import re

from agent.constants import MARKER_TAG_RE
from agent.errors import RecoverableAgentError


def validate_marker_syntax(text: str) -> None:
    invalid_tokens = [
        token
        for token in MARKER_TAG_RE.findall(text)
        if token not in {"<R>", "<C>", "</C>"}
    ]
    if invalid_tokens:
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            "回复中包含非法隐藏事件标记。",
            raw_output=text,
            details={"invalid_tokens": invalid_tokens},
        )
    if text.count("<R>") > 1:
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            "回复中只能出现一个 <R> 推荐标记。",
            raw_output=text,
            details={"marker": "R", "open_count": text.count("<R>")},
        )
    if text.count("<C>") != text.count("</C>"):
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            "<C> 标记未正确闭合。",
            raw_output=text,
            details={
                "marker": "C",
                "open_count": text.count("<C>"),
                "close_count": text.count("</C>"),
            },
        )


def ensure_marker_is_first_line(text: str, match: re.Match, marker_name: str) -> None:
    if text[: match.start()].strip():
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            f"{marker_name} 标记必须位于最终回复第一行开头。",
            raw_output=text,
            details={"marker": marker_name},
        )


def strip_hidden_event_marker_text(text: str) -> str:
    text = re.sub(r"<R>.*", "", text, flags=re.DOTALL)
    return re.sub(r"<C>.*?</C>\n?", "", text, flags=re.DOTALL)
