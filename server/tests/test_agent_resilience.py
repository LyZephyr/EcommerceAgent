from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent.graph as agent_graph  # noqa: E402
import agent.runtime as agent_runtime  # noqa: E402
import agent.tool_runtime as tool_runtime  # noqa: E402
from agent import (  # noqa: E402
    AgentRecoveryExhausted,
    BlockProductEvent,
    BlockTextDeltaEvent,
    BlockTextEvent,
    CartEvent,
    MessageResetEvent,
    RecoverableAgentError,
    RecoveryState,
    ToolCall,
    SYSTEM_PROMPT,
    StreamingFinalEmitter,
    events_from_parsed_response,
    parse_final_response,
    recommendation_history_text,
)
from agent.constants import MAX_TOOL_STEPS  # noqa: E402


def test_system_prompt_limits_mobile_visible_output() -> None:
    assert "禁止输出 Markdown 标题、Markdown 表格" in SYSTEM_PROMPT
    assert "###、**、|、---" in SYSTEM_PROMPT
    assert "120 个中文字符以内" in SYSTEM_PROMPT
    assert "商品标题、价格、品牌、规格、库存、图片和加购入口由客户端商品卡片展示" in SYSTEM_PROMPT
    assert "同时包含多个购物车操作" in SYSTEM_PROMPT
    assert "只能包含工具调用" in SYSTEM_PROMPT
    assert "只能包含正文" in SYSTEM_PROMPT
    assert "<INTRO>" in SYSTEM_PROMPT
    assert '<ITEM id="商品ID">' in SYSTEM_PROMPT
    assert "不要写 <REASON>" in SYSTEM_PROMPT
    assert "不要输出 </R>" in SYSTEM_PROMPT
    assert MAX_TOOL_STEPS == 5


def test_parse_final_response_accepts_plain_text_without_recommend_marker() -> None:
    parsed = parse_final_response(
        "当前候选商品不符合你的需求，建议放宽条件再试。",
        candidate_ids={"p1"},
    )

    assert parsed.recommendation is None
    assert parsed.clean_text == "当前候选商品不符合你的需求，建议放宽条件再试。"


def test_parse_final_response_accepts_valid_recommend_marker() -> None:
    parsed = parse_final_response(
        """<R>
<INTRO>整体建议：早餐优先选常温奶。
<ITEM id="p1">这款口感稳定，适合家庭早餐。
<ITEM id="p2">这款更适合看重低脂负担的人。
<OUTRO>按饮用频率选就好。""",
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
        parse_final_response(
            """<R>
<INTRO>整体建议：早餐优先选常温奶。
<ITEM id="p1">**这款**更合适。""",
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == "visible_reply_markdown"


def test_parse_final_response_rejects_long_recommendation_text() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        parse_final_response(
            f"""<R>
<INTRO>整体建议：早餐优先选常温奶。
<ITEM id="p1">{'这款商品适合日常饮用，口感稳定，规格方便，适合家庭囤货。' * 3}""",
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == "visible_reply_too_long"


def test_parse_final_response_rejects_conflicting_markers() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        parse_final_response(
            '<R><INTRO>建议。<ITEM id="p1">理由。'
            '<C>{"products":[],"rows":[]}</C>',
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == "hidden_marker_invalid"


def test_parse_final_response_rejects_invalid_compare_json() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        parse_final_response(
            "<C>{bad json}</C>\n对比结论。",
            candidate_ids=set(),
        )

    assert exc_info.value.error_type == "compare_marker_invalid_json"


def test_parse_final_response_accepts_grouped_recommendation() -> None:
    parsed = parse_final_response(
        """<R>
<INTRO>整体建议：海边出行先防晒，再补轻薄外套。
<ITEM id="s1" group="防晒护肤">这款适合长时间户外使用。
<ITEM id="j1" group="度假穿搭">这款轻薄好收纳，适合早晚温差。""",
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
            '<R><INTRO>建议。<ITEM id="bad">理由。',
            "recommend_marker_unknown_ids",
        ),
        (
            '<R><INTRO>建议。<ITEM id="p1" group="多余">理由。',
            "recommend_marker_invalid_group",
        ),
        (
            '<R><INTRO>建议。<ITEM id="p1?">理由。',
            "recommend_marker_invalid_attr",
        ),
        (
            '<R><INTRO>建议。<ITEM id="p1">',
            "recommend_marker_empty_reason",
        ),
        (
            '<R><INTRO>建议。<ITEM id="p1">理由。<INTRO>嵌套',
            "recommend_marker_invalid",
        ),
    ],
)
def test_parse_final_response_rejects_invalid_recommendation(body: str, error_type: str) -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        parse_final_response(
            body,
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == error_type


def test_parse_final_response_rejects_visible_text_outside_recommendation() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        parse_final_response(
            '前言<R><INTRO>建议。<ITEM id="p1">理由。',
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == "hidden_marker_invalid"


def test_parse_final_response_rejects_legacy_recommendation_closing_tags() -> None:
    with pytest.raises(RecoverableAgentError) as exc_info:
        parse_final_response(
            '<R><INTRO>建议。</INTRO><ITEM id="p1"><REASON>理由。</REASON></ITEM></R>',
            candidate_ids={"p1"},
        )

    assert exc_info.value.error_type == "hidden_marker_invalid"


def test_events_from_recommendation_keep_block_order() -> None:
    parsed = parse_final_response(
        """<R>
<INTRO>整体建议：早餐优先选常温奶。
<ITEM id="p1">这款口感稳定，适合家庭早餐。
<ITEM id="p2">这款更适合看重低脂负担的人。
<OUTRO>按饮用频率选就好。""",
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
    parsed = parse_final_response(
        '<R><INTRO>整体建议：选第一款。<ITEM id="p1">理由短。',
        candidate_ids={"p1"},
    )

    history_text = recommendation_history_text(
        parsed.recommendation,
        {"p1": _product("p1", "测试牛奶")},
    )

    assert "[商品] 测试牛奶（product_id=p1）：理由短。" in history_text


def test_streaming_recommendation_emits_product_before_reason_delta() -> None:
    emitter = StreamingFinalEmitter(
        message_id="asst-test",
        attempt_id="attempt-1",
        candidates_by_id={"p1": _product("p1", "测试牛奶")},
        candidate_groups=[],
    )

    events = []
    for chunk in [
        "<",
        "R><INTRO>整体建议：选常温奶。",
        '<ITEM id="p1">',
        "口感稳定，适合早餐。",
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


def test_streaming_recommendation_trims_segment_boundary_whitespace() -> None:
    emitter = StreamingFinalEmitter(
        message_id="asst-test",
        attempt_id="attempt-1",
        candidates_by_id={
            "p1": _product("p1", "测试牛奶"),
            "p2": _product("p2", "低脂牛奶"),
        },
        candidate_groups=[],
    )

    events = emitter.feed(
        """<R>
<INTRO>整体建议：优先选常温奶。
<ITEM id="p1">
口感稳定，适合早餐。
<ITEM id="p2">低脂负担更轻。
"""
    )
    emitter.finish()

    text_by_block: dict[str, str] = {}
    for event in events:
        if isinstance(event, BlockTextDeltaEvent):
            text_by_block[event.block_id] = (
                text_by_block.get(event.block_id, "") + event.content
            )

    assert text_by_block == {
        "blk-1": "整体建议：优先选常温奶。",
        "blk-3": "口感稳定，适合早餐。",
        "blk-5": "低脂负担更轻。",
    }


def test_streaming_recommendation_keeps_unicode_chunks_valid() -> None:
    emitter = StreamingFinalEmitter(
        message_id="asst-test",
        attempt_id="attempt-1",
        candidates_by_id={"p1": _product("p1", "测试牛奶")},
        candidate_groups=[],
    )

    events = emitter.feed(
        '<R><INTRO>整体建议：选🥛。<ITEM id="p1">'
        "适合早餐😊。"
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


def test_parse_tool_arguments_rejects_invalid_json_arguments() -> None:
    tool_call = ToolCall(
        id="call_1",
        name="retrieve_products",
        arguments='{"requests": [',
    )

    with pytest.raises(RecoverableAgentError) as exc_info:
        tool_runtime.parse_tool_arguments(tool_call)

    assert exc_info.value.error_type == "tool_arguments_invalid"
    assert exc_info.value.tool_name == "retrieve_products"


def test_recovery_state_allows_two_retries_then_exhausts() -> None:
    state = RecoveryState()
    error = RecoverableAgentError("hidden_marker_invalid", "bad marker")

    assert '"retry_count": 1' in state.record(error, label="test")
    assert '"retry_count": 2' in state.record(error, label="test")
    with pytest.raises(AgentRecoveryExhausted):
        state.record(error, label="test")


def test_run_turn_continues_after_cart_tool_for_compound_request(monkeypatch) -> None:
    monkeypatch.setattr(agent_graph, "ARK_API_KEY", "test-key")
    streams = [
        _stream(
            [
                _tool_chunk(
                    "call-remove",
                    "remove_from_cart",
                    {"cart_position": 1},
                )
            ]
        ),
        _stream(
            [
                _tool_chunk(
                    "call-update",
                    "update_cart_item",
                    {"cart_position": 1, "quantity": 2},
                )
            ]
        ),
        _stream([_content_chunk("已删除第一件，并把第二件数量改为 2 件。")]),
    ]
    executed_tools = []

    async def fake_create_stream(_state, **_kwargs):
        return streams.pop(0)

    def fake_execute_tool(name, arguments, conversation_id=None):
        executed_tools.append((name, arguments, conversation_id))
        return {
            "success": True,
            "message": "ok",
            "cart": {
                "conversation_id": conversation_id,
                "items": [],
                "total_quantity": 0,
                "total_price": 0.0,
                "messages": [],
            },
        }

    monkeypatch.setattr(agent_runtime, "create_stream", fake_create_stream)
    monkeypatch.setattr(tool_runtime, "execute_tool", fake_execute_tool)

    events = asyncio.run(
        _collect_turn_events(
            agent_graph.run_turn(
                "compound-cart-test",
                "帮我移除购物车里的第一件商品，并将第二件商品的数量修改为2",
            )
        )
    )

    assert [name for name, _arguments, _conversation_id in executed_tools] == [
        "remove_from_cart",
        "update_cart_item",
    ]
    assert not streams
    assert any(isinstance(event, CartEvent) for event in events)
    text = "".join(
        event.content for event in events if isinstance(event, BlockTextDeltaEvent)
    )
    assert text == "已删除第一件，并把第二件数量改为 2 件。"


def test_run_turn_continues_after_retrieve_tool_before_streaming_final(monkeypatch) -> None:
    monkeypatch.setattr(agent_graph, "ARK_API_KEY", "test-key")
    streams = [
        _stream(
            [
                _tool_chunk(
                    "call-retrieve",
                    "retrieve_products",
                    {"requests": [{"search_query": "牛奶"}]},
                )
            ]
        ),
        _stream([_tool_chunk("call-cart", "view_cart", {})]),
        _stream([_content_chunk("推荐测试牛奶。")]),
    ]
    executed_tools = []

    async def fake_create_stream(_state, **_kwargs):
        return streams.pop(0)

    def fake_execute_tool(name, arguments, conversation_id=None):
        executed_tools.append((name, arguments, conversation_id))
        if name == "retrieve_products":
            return [
                {
                    "label": "牛奶",
                    "search_query": "牛奶",
                    "products": [_product("p1", "测试牛奶")],
                }
            ]
        return {
            "success": True,
            "message": "购物车为空。",
            "cart": {
                "conversation_id": conversation_id,
                "items": [],
                "total_quantity": 0,
                "total_price": 0.0,
                "messages": [],
            },
        }

    monkeypatch.setattr(agent_runtime, "create_stream", fake_create_stream)
    monkeypatch.setattr(tool_runtime, "execute_tool", fake_execute_tool)

    events = asyncio.run(
        _collect_turn_events(
            agent_graph.run_turn("retrieve-loop-test", "推荐牛奶，再看看购物车")
        )
    )

    assert [name for name, _arguments, _conversation_id in executed_tools] == [
        "retrieve_products",
        "view_cart",
    ]
    assert not streams
    assert any(
        isinstance(event, BlockTextDeltaEvent) and event.content
        for event in events
    )


def test_run_turn_resets_provisional_text_when_tool_call_arrives(monkeypatch) -> None:
    monkeypatch.setattr(agent_graph, "ARK_API_KEY", "test-key")
    streams = [
        _stream(
            [
                _content_chunk("我先看一下"),
                _tool_chunk(
                    "call-retrieve",
                    "retrieve_products",
                    {"requests": [{"search_query": "牛奶"}]},
                ),
            ]
        ),
        _stream([_content_chunk("没有找到更合适的商品。")]),
    ]

    async def fake_create_stream(_state, **_kwargs):
        return streams.pop(0)

    def fake_execute_tool(name, _arguments, conversation_id=None):
        assert name == "retrieve_products"
        assert conversation_id is None
        return []

    monkeypatch.setattr(agent_runtime, "create_stream", fake_create_stream)
    monkeypatch.setattr(tool_runtime, "execute_tool", fake_execute_tool)

    events = asyncio.run(
        _collect_turn_events(agent_graph.run_turn("reset-test", "推荐牛奶"))
    )

    assert any(
        isinstance(event, MessageResetEvent)
        and event.reason == "tool_call_after_text"
        for event in events
    )
    text = "".join(
        event.content for event in events if isinstance(event, BlockTextDeltaEvent)
    )
    assert "没有找到更合适的商品。" in text


def test_run_turn_force_final_tool_call_exhausts_without_loop(monkeypatch) -> None:
    monkeypatch.setattr(agent_graph, "ARK_API_KEY", "test-key")
    streams = [
        _stream([_tool_chunk(f"call-view-{index}", "view_cart", {})])
        for index in range(MAX_TOOL_STEPS)
    ]
    streams.append(_stream([_tool_chunk("call-after-limit", "view_cart", {})]))

    async def fake_create_stream(_state, **_kwargs):
        return streams.pop(0)

    def fake_execute_tool(name, arguments, conversation_id=None):
        return {
            "success": True,
            "message": f"{name} ok",
            "cart": {
                "conversation_id": conversation_id,
                "items": [],
                "total_quantity": 0,
                "total_price": 0.0,
                "messages": [],
            },
        }

    monkeypatch.setattr(agent_runtime, "create_stream", fake_create_stream)
    monkeypatch.setattr(tool_runtime, "execute_tool", fake_execute_tool)

    with pytest.raises(AgentRecoveryExhausted) as exc_info:
        asyncio.run(
            _collect_turn_events(agent_graph.run_turn("force-final-test", "查看购物车"))
        )

    assert exc_info.value.error.error_type == "force_final_tool_call"
    assert not streams


def test_run_turn_times_out_during_stream_iteration(monkeypatch) -> None:
    monkeypatch.setattr(agent_graph, "ARK_API_KEY", "test-key")
    monkeypatch.setattr(agent_runtime, "LLM_TIMEOUT_SECONDS", 0.01)

    async def fake_create_stream(_state, **_kwargs):
        return _HangingStream()

    monkeypatch.setattr(agent_runtime, "create_stream", fake_create_stream)

    with pytest.raises(AgentRecoveryExhausted) as exc_info:
        asyncio.run(
            _collect_turn_events(agent_graph.run_turn("stream-timeout-test", "推荐牛奶"))
        )

    assert exc_info.value.error.error_type == "llm_timeout"


async def _collect_events(parsed, candidates):
    return [
        event
        async for event in events_from_parsed_response(
            parsed,
            candidates,
            message_id="asst-test",
        )
    ]


async def _collect_turn_events(events):
    return await asyncio.wait_for(_collect_turn_events_unbounded(events), timeout=2)


async def _collect_turn_events_unbounded(events):
    return [event async for event in events]


def _stream(chunks):
    return _FakeStream(chunks)


def _content_chunk(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


def _tool_chunk(call_id: str, name: str, arguments: dict):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id=call_id,
                            type="function",
                            function=SimpleNamespace(
                                name=name,
                                arguments=json.dumps(arguments, ensure_ascii=False),
                            ),
                        )
                    ]
                )
            )
        ]
    )


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def aclose(self):
        return None


class _HangingStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(1)
        raise StopAsyncIteration

    async def aclose(self):
        return None


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
