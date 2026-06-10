from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import (  # noqa: E402
    AgentRecoveryExhausted,
    BlockProductEvent,
    BlockTextDeltaEvent,
    BlockTextEvent,
    RecoverableAgentError,
    RecoveryState,
    SYSTEM_PROMPT,
    _StreamingFinalEmitter,
    _events_from_parsed_response,
    _parse_final_response,
    _parse_tool_call,
    _recommendation_history_text,
)


def test_system_prompt_limits_mobile_visible_output() -> None:
    assert "禁止输出 Markdown 标题、Markdown 表格" in SYSTEM_PROMPT
    assert "###、**、|、---" in SYSTEM_PROMPT
    assert "120 个中文字符以内" in SYSTEM_PROMPT
    assert "商品标题、价格、品牌、规格、库存、图片和加购入口由客户端商品卡片展示" in SYSTEM_PROMPT
    assert "<INTRO>" in SYSTEM_PROMPT
    assert '<ITEM id="商品ID">' in SYSTEM_PROMPT


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
        """<R>
<INTRO>整体建议：早餐优先选常温奶。</INTRO>
<ITEM id="p1">
<REASON>这款口感稳定，适合家庭早餐。</REASON>
</ITEM>
<ITEM id="p2">
<REASON>这款更适合看重低脂负担的人。</REASON>
</ITEM>
<OUTRO>按饮用频率选就好。</OUTRO>
</R>""",
        require_recommend_marker=True,
        candidate_ids={"p1", "p2"},
    )

    assert parsed.recommended_ids == ["p1", "p2"]
    assert parsed.compare_payload is None
    assert parsed.clean_text.splitlines() == [
        "整体建议：早餐优先选常温奶。",
        "这款口感稳定，适合家庭早餐。",
        "这款更适合看重低脂负担的人。",
        "按饮用频率选就好。",
    ]


def test_parse_final_response_rejects_visible_markdown() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        _parse_final_response(
            """<R>
<INTRO>整体建议：早餐优先选常温奶。</INTRO>
<ITEM id="p1">
<REASON>**这款**更合适。</REASON>
</ITEM>
</R>""",
            require_recommend_marker=True,
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == "visible_reply_markdown"


def test_parse_final_response_rejects_long_recommendation_text() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        _parse_final_response(
            f"""<R>
<INTRO>整体建议：早餐优先选常温奶。</INTRO>
<ITEM id="p1">
<REASON>{'这款商品适合日常饮用，口感稳定，规格方便，适合家庭囤货。' * 3}</REASON>
</ITEM>
</R>""",
            require_recommend_marker=True,
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == "visible_reply_too_long"


def test_parse_final_response_rejects_conflicting_markers() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        _parse_final_response(
            '<R><INTRO>建议。</INTRO><ITEM id="p1"><REASON>理由。</REASON></ITEM></R>'
            '<C>{"products":[],"rows":[]}</C>',
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


def test_parse_final_response_accepts_grouped_recommendation() -> None:
    parsed = _parse_final_response(
        """<R>
<INTRO>整体建议：海边出行先防晒，再补轻薄外套。</INTRO>
<ITEM id="s1" group="防晒护肤">
<REASON>这款适合长时间户外使用。</REASON>
</ITEM>
<ITEM id="j1" group="度假穿搭">
<REASON>这款轻薄好收纳，适合早晚温差。</REASON>
</ITEM>
</R>""",
        require_recommend_marker=True,
        candidate_ids={"s1", "j1"},
        candidate_groups=[
            {"label": "防晒护肤", "products": [{"product_id": "s1"}]},
            {"label": "度假穿搭", "products": [{"product_id": "j1"}]},
        ],
    )

    assert [item.group for item in parsed.recommendation.items] == [
        "防晒护肤",
        "度假穿搭",
    ]


@pytest.mark.parametrize(
    ("body", "error_type"),
    [
        (
            '<R><INTRO>建议。</INTRO><ITEM id="bad"><REASON>理由。</REASON></ITEM></R>',
            "recommend_marker_unknown_ids",
        ),
        (
            '<R><INTRO>建议。</INTRO><ITEM id="p1" group="多余"><REASON>理由。</REASON></ITEM></R>',
            "recommend_marker_invalid_group",
        ),
        (
            '<R><INTRO>建议。</INTRO><ITEM id="p1?"><REASON>理由。</REASON></ITEM></R>',
            "recommend_marker_invalid_attr",
        ),
        (
            '<R><INTRO>建议。</INTRO><ITEM id="p1"><REASON></REASON></ITEM></R>',
            "recommend_marker_empty_reason",
        ),
        (
            '<R><INTRO>建议。</INTRO><ITEM id="p1"><INTRO>嵌套</INTRO><REASON>理由。</REASON></ITEM></R>',
            "recommend_marker_invalid",
        ),
    ],
)
def test_parse_final_response_rejects_invalid_recommendation(body: str, error_type: str) -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        _parse_final_response(
            body,
            require_recommend_marker=True,
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == error_type


def test_parse_final_response_rejects_visible_text_outside_recommendation() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        _parse_final_response(
            '前言<R><INTRO>建议。</INTRO><ITEM id="p1"><REASON>理由。</REASON></ITEM></R>',
            require_recommend_marker=True,
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == "recommend_marker_visible_text_outside"


def test_events_from_recommendation_keep_block_order() -> None:
    parsed = _parse_final_response(
        """<R>
<INTRO>整体建议：早餐优先选常温奶。</INTRO>
<ITEM id="p1">
<REASON>这款口感稳定，适合家庭早餐。</REASON>
</ITEM>
<ITEM id="p2">
<REASON>这款更适合看重低脂负担的人。</REASON>
</ITEM>
<OUTRO>按饮用频率选就好。</OUTRO>
</R>""",
        require_recommend_marker=True,
        candidate_ids={"p1", "p2"},
    )
    candidates = {
        "p1": _product("p1", "商品一"),
        "p2": _product("p2", "商品二"),
    }

    events = asyncio.run(_collect_events(parsed, candidates))
    block_events = [
        event for event in events if isinstance(event, (BlockTextEvent, BlockProductEvent))
    ]

    assert [(type(event).__name__, event.block_id) for event in block_events] == [
        ("BlockTextEvent", "blk-1"),
        ("BlockProductEvent", "blk-2"),
        ("BlockTextEvent", "blk-3"),
        ("BlockProductEvent", "blk-4"),
        ("BlockTextEvent", "blk-5"),
        ("BlockTextEvent", "blk-6"),
    ]
    assert block_events[1].product_id == "p1"
    assert block_events[3].product_id == "p2"


def test_recommendation_history_contains_product_title_id_and_reason() -> None:
    parsed = _parse_final_response(
        '<R><INTRO>整体建议：选第一款。</INTRO><ITEM id="p1"><REASON>理由短。</REASON></ITEM></R>',
        require_recommend_marker=True,
        candidate_ids={"p1"},
    )

    history_text = _recommendation_history_text(
        parsed.recommendation,
        {"p1": _product("p1", "测试牛奶")},
    )

    assert "[商品] 测试牛奶（product_id=p1）：理由短。" in history_text


def test_streaming_recommendation_emits_product_before_reason_delta() -> None:
    emitter = _StreamingFinalEmitter(
        message_id="asst-test",
        candidates_by_id={"p1": _product("p1", "测试牛奶")},
        candidate_groups=[],
        require_recommend_marker=True,
    )

    events = []
    for chunk in [
        "<",
        "R><INTRO>整体建议：选常温奶。</INTRO>",
        '<ITEM id="p1">',
        "<REASON>口感稳定，适合早餐。</REASON></ITEM></R>",
    ]:
        events.extend(emitter.feed(chunk))
    parsed = emitter.finish()

    visible_chunks = [
        event.content for event in events if isinstance(event, BlockTextDeltaEvent)
    ]
    assert "<R>" not in "".join(visible_chunks)
    assert "<ITEM" not in "".join(visible_chunks)
    product_index = next(
        index for index, event in enumerate(events) if isinstance(event, BlockProductEvent)
    )
    reason_index = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, BlockTextDeltaEvent) and event.block_id == "blk-3"
    )
    assert product_index < reason_index
    assert parsed.recommended_ids == ["p1"]


def test_streaming_recommendation_keeps_unicode_chunks_valid() -> None:
    emitter = _StreamingFinalEmitter(
        message_id="asst-test",
        candidates_by_id={"p1": _product("p1", "测试牛奶")},
        candidate_groups=[],
        require_recommend_marker=True,
    )

    events = emitter.feed(
        '<R><INTRO>整体建议：选🥛。</INTRO><ITEM id="p1">'
        "<REASON>适合早餐😊。</REASON></ITEM></R>"
    )
    emitter.finish()

    assert all(
        isinstance(event.content, str)
        for event in events
        if isinstance(event, BlockTextDeltaEvent)
    )
    assert "🥛" in "".join(
        event.content for event in events if isinstance(event, BlockTextDeltaEvent)
    )


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


async def _collect_events(parsed, candidates):
    return [
        event
        async for event in _events_from_parsed_response(
            parsed,
            candidates,
            message_id="asst-test",
        )
    ]


def _product(product_id: str, title: str) -> dict:
    return {
        "product_id": product_id,
        "title": title,
        "brand": "测试品牌",
        "category": "食品饮料",
        "sub_category": "牛奶",
        "price": 12.0,
        "image_url": "/assets/test.jpg",
        "stock": 3,
        "is_active": True,
    }
