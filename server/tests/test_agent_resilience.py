from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import (  # noqa: E402
    AgentRecoveryExhausted,
    RecoverableAgentError,
    RecoveryState,
    _parse_final_response,
    _parse_tool_call,
)


def test_parse_final_response_requires_recommend_marker_after_retrieval() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        _parse_final_response(
            "这款商品比较适合你。",
            require_recommend_marker=True,
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == "recommend_marker_missing"


def test_parse_final_response_accepts_valid_recommend_marker() -> None:
    parsed = _parse_final_response(
        "<R>p1,p2</R>\n推荐 p1 和 p2。",
        require_recommend_marker=True,
        candidate_ids={"p1", "p2"},
    )

    assert parsed.recommended_ids == ["p1", "p2"]
    assert parsed.compare_payload is None
    assert parsed.clean_text.strip() == "推荐 p1 和 p2。"


def test_parse_final_response_rejects_conflicting_markers() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        _parse_final_response(
            '<R>p1</R>\n<C>{"products":[],"rows":[]}</C>\n正文',
            require_recommend_marker=True,
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == "hidden_marker_invalid"


def test_parse_final_response_rejects_invalid_compare_json() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        _parse_final_response(
            "<C>{bad json}</C>\n对比结论。",
            require_recommend_marker=False,
            candidate_ids=set(),
        )

    assert exc_info.value.error_type == "compare_marker_invalid_json"


def test_parse_tool_call_rejects_invalid_json_arguments() -> None:
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="retrieve_products",
            arguments='{"requests": [',
        ),
    )

    with pytest.raises(RecoverableAgentError) as exc_info:
        _parse_tool_call(tool_call)

    assert exc_info.value.error_type == "tool_arguments_invalid"
    assert exc_info.value.tool_name == "retrieve_products"


def test_recovery_state_allows_two_retries_then_exhausts() -> None:
    state = RecoveryState()
    error = RecoverableAgentError("hidden_marker_invalid", "bad marker")

    assert '"retry_count": 1' in state.record(error, label="test")
    assert '"retry_count": 2' in state.record(error, label="test")
    with pytest.raises(AgentRecoveryExhausted):
        state.record(error, label="test")
