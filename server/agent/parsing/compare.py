"""<C> 对比标记解析。"""

from __future__ import annotations

import json

from agent.errors import RecoverableAgentError


def loads_compare_payload_or_raise(raw_json: str, *, raw_output: str) -> dict:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RecoverableAgentError(
            "compare_marker_invalid_json",
            f"<C> 标记内容不是合法 JSON：{exc}",
            raw_output=raw_output,
            details={"exception_type": type(exc).__name__},
        ) from exc
    if not isinstance(payload, dict):
        raise RecoverableAgentError(
            "compare_marker_invalid_json",
            "<C> 标记内容必须是 JSON object。",
            raw_output=raw_output,
            details={"actual_type": type(payload).__name__},
        )
    if not isinstance(payload.get("products"), list) or not isinstance(
        payload.get("rows"),
        list,
    ):
        raise RecoverableAgentError(
            "compare_marker_invalid_schema",
            '<C> 标记 JSON 必须包含 products[] 和 rows[]。',
            raw_output=raw_output,
            details={"keys": sorted(payload)},
        )
    return payload
