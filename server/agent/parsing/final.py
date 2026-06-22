"""最终回复解析编排。"""

from __future__ import annotations

import re

from agent.errors import RecoverableAgentError
from agent.events import ParsedFinalResponse
from agent.parsing.compare import loads_compare_payload_or_raise
from agent.parsing.markers import (
    ensure_marker_is_first_line,
    strip_hidden_event_marker_text,
    validate_marker_syntax,
)
from agent.parsing.mobile import validate_mobile_visible_reply
from agent.parsing.recommend import (
    parse_recommendation_marker,
    recommendation_visible_text,
)


def parse_final_response(
    text: str,
    *,
    candidate_ids: set[str],
    candidate_groups: list[dict] | None = None,
) -> ParsedFinalResponse:
    validate_marker_syntax(text)
    recommend_matches = list(re.finditer(r"<R>", text))
    compare_matches = list(re.finditer(r"<C>(.*?)</C>\n?", text, flags=re.DOTALL))

    if len(recommend_matches) > 1:
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            "回复中只能出现一个 <R> 推荐标记。",
            raw_output=text,
            details={"recommend_marker_count": len(recommend_matches)},
        )
    if len(compare_matches) > 1:
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            "回复中只能出现一个 <C> 对比标记。",
            raw_output=text,
            details={"compare_marker_count": len(compare_matches)},
        )
    if recommend_matches and compare_matches:
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            "<R> 和 <C> 不能同时出现在同一条回复中。",
            raw_output=text,
        )
    if recommend_matches:
        recommend_match = recommend_matches[0]
        ensure_marker_is_first_line(text, recommend_match, "<R>")
        recommendation = parse_recommendation_marker(
            text[recommend_match.start() :].strip(),
            raw_output=text,
            candidate_ids=candidate_ids,
            candidate_groups=candidate_groups or [],
        )
        clean_text = recommendation_visible_text(recommendation)
        return ParsedFinalResponse(recommendation, None, clean_text)

    clean_text = strip_hidden_event_marker_text(text)
    if not clean_text.strip():
        raise RecoverableAgentError(
            "visible_reply_empty",
            "去除隐藏事件标记后，用户可见回复为空。",
            raw_output=text,
        )

    if compare_matches:
        compare_match = compare_matches[0]
        ensure_marker_is_first_line(text, compare_match, "<C>")
        compare_payload = loads_compare_payload_or_raise(
            compare_match.group(1),
            raw_output=text,
        )
        validate_mobile_visible_reply(
            clean_text,
            raw_output=text,
            enforce_length=True,
        )
        return ParsedFinalResponse(None, compare_payload, clean_text)

    validate_mobile_visible_reply(
        text,
        raw_output=text,
        enforce_length=False,
    )
    return ParsedFinalResponse(None, None, text)
