from __future__ import annotations

import json

from agent.events import (
    BlockCompareEvent,
    BlockProductEvent,
    BlockTextDeltaEvent,
    BlockTextEvent,
    CartEvent,
    MessageCommitEvent,
    MessageResetEvent,
    MessageStartEvent,
    StructuredStatusEvent,
)
from sse.mapper import (
    GENERIC_ERROR_MESSAGE,
    RECOVERY_EXHAUSTED_MESSAGE,
    map_agent_event,
    map_block_product_event,
    map_done_event,
    map_error_event,
)


def test_map_block_text_event() -> None:
    event = BlockTextEvent(message_id="m1", block_id="blk-1", content="你好")
    mapped = map_agent_event(event, conversation_id="conv-1")

    assert mapped is not None
    assert mapped["event"] == "block"
    payload = json.loads(mapped["data"])
    assert payload == {
        "type": "text",
        "message_id": "m1",
        "attempt_id": "attempt-1",
        "block_id": "blk-1",
        "content": "你好",
    }


def test_map_block_text_delta_event() -> None:
    event = BlockTextDeltaEvent(message_id="m1", block_id="blk-2", content="推")
    mapped = map_agent_event(event, conversation_id="conv-1")

    assert mapped is not None
    payload = json.loads(mapped["data"])
    assert payload["type"] == "text_delta"
    assert payload["attempt_id"] == "attempt-1"
    assert payload["content"] == "推"


def test_map_block_product_event_does_not_record_recent_product(monkeypatch) -> None:
    recorded: list[tuple[str, dict]] = []

    def fake_record(conversation_id: str, product: dict) -> None:
        recorded.append((conversation_id, product))

    monkeypatch.setattr("sse.mapper.cart_store.record_recent_product", fake_record)

    product_data = {
        "product_id": "p1",
        "title": "测试牛奶",
        "brand": "测试品牌",
        "category": "食品饮料",
        "sub_category": "牛奶",
        "price": 12.0,
        "image_url": "/assets/p1.jpg",
        "stock": 2,
        "is_active": True,
        "raw_payload": json.dumps({"product_id": "p1"}, ensure_ascii=False),
    }
    event = BlockProductEvent(
        message_id="m1",
        block_id="blk-3",
        product_id="p1",
        product_data=product_data,
        group="早餐",
    )
    mapped = map_block_product_event(event)

    assert mapped["event"] == "block"
    payload = json.loads(mapped["data"])
    assert payload["type"] == "product"
    assert payload["group"] == "早餐"
    assert payload["product"]["product_id"] == "p1"
    assert payload["product"]["detail_url"] == "/api/products/p1"
    assert recorded == []


def test_map_message_lifecycle_events_record_recent_products_on_commit(monkeypatch) -> None:
    recorded: list[tuple[str, dict]] = []

    def fake_record(conversation_id: str, product: dict) -> None:
        recorded.append((conversation_id, product))

    monkeypatch.setattr("sse.mapper.cart_store.record_recent_product", fake_record)

    product_data = {
        "product_id": "p1",
        "title": "测试牛奶",
        "brand": "测试品牌",
        "category": "食品饮料",
        "sub_category": "牛奶",
        "price": 12.0,
        "image_url": "/assets/p1.jpg",
        "stock": 2,
        "is_active": True,
    }

    start = map_agent_event(
        MessageStartEvent(message_id="m1", attempt_id="attempt-1"),
        conversation_id="conv-1",
    )
    reset = map_agent_event(
        MessageResetEvent(message_id="m1", attempt_id="attempt-1", reason="retry"),
        conversation_id="conv-1",
    )
    commit = map_agent_event(
        MessageCommitEvent(
            message_id="m1",
            attempt_id="attempt-2",
            recent_products=[{"product_data": product_data, "group": "早餐"}],
        ),
        conversation_id="conv-1",
    )

    assert start["event"] == "message_start"
    assert json.loads(start["data"])["provisional"] is True
    assert reset["event"] == "message_reset"
    assert json.loads(reset["data"])["reason"] == "retry"
    assert commit["event"] == "message_commit"
    assert recorded[0][0] == "conv-1"
    assert recorded[0][1]["product_id"] == "p1"
    assert recorded[0][1]["group_label"] == "早餐"


def test_map_compare_and_status_events() -> None:
    compare = map_agent_event(
        BlockCompareEvent(
            message_id="m1",
            block_id="blk-1",
            payload={"products": [], "rows": []},
        ),
        conversation_id="conv-1",
    )
    status = map_agent_event(
        StructuredStatusEvent(
            phase="retrieving",
            message="正在检索商品...",
        ),
        conversation_id="conv-1",
    )

    assert json.loads(compare["data"])["type"] == "compare"
    status_data = json.loads(status["data"])
    assert status_data["phase"] == "retrieving"
    assert status_data["step"] is None
    assert status_data["total_steps"] is None


def test_map_cart_and_terminal_events() -> None:
    cart = map_agent_event(
        CartEvent({"items": [], "total_quantity": 0, "total_price": 0.0, "messages": []}),
        conversation_id="conv-1",
    )

    assert cart["event"] == "cart"
    assert map_done_event() == {"event": "done", "data": "{}"}
    assert json.loads(map_error_event(RECOVERY_EXHAUSTED_MESSAGE)["data"])["message"] == (
        RECOVERY_EXHAUSTED_MESSAGE
    )
    assert json.loads(map_error_event(GENERIC_ERROR_MESSAGE)["data"])["message"] == (
        GENERIC_ERROR_MESSAGE
    )
