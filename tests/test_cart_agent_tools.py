from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import cart_store  # noqa: E402
import main  # noqa: E402
from agent import CartEvent, TokenEvent  # noqa: E402
from tools import execute  # noqa: E402


def test_cart_tool_adds_recent_product_by_position():
    conversation_id = uuid4().hex
    cart_store.record_recent_product(conversation_id, _product("p-1", title="第一款"))
    cart_store.record_recent_product(conversation_id, _product("p-2", title="第二款"))

    result = execute(
        "add_to_cart",
        {"recent_position": 2, "quantity": 2},
        conversation_id,
    )

    assert result["success"] is True
    assert result["cart"]["items"][0]["product_id"] == "p-2"
    assert result["cart"]["items"][0]["quantity"] == 2
    assert result["cart"]["total_quantity"] == 2


def test_cart_tool_updates_and_removes_by_keyword():
    conversation_id = uuid4().hex
    cart_store.record_recent_product(
        conversation_id,
        _product("p-1", title="轻量蓝牙耳机", category="数码电子"),
    )
    execute("add_to_cart", {"title_keyword": "耳机"}, conversation_id)

    updated = execute(
        "update_cart_item",
        {"title_keyword": "耳机", "quantity": 3},
        conversation_id,
    )
    removed = execute("remove_from_cart", {"title_keyword": "耳机"}, conversation_id)

    assert updated["success"] is True
    assert updated["cart"]["items"][0]["quantity"] == 3
    assert removed["success"] is True
    assert removed["cart"]["items"] == []


def test_cart_tool_rejects_ambiguous_recent_reference():
    conversation_id = uuid4().hex
    cart_store.record_recent_product(conversation_id, _product("p-1", title="第一款"))
    cart_store.record_recent_product(conversation_id, _product("p-2", title="第二款"))

    result = execute("add_to_cart", {}, conversation_id)

    assert result["success"] is False
    assert "哪一款" in result["message"]
    assert cart_store.snapshot(conversation_id)["items"] == []


def test_chat_stream_emits_cart_event(monkeypatch):
    asyncio.run(_test_chat_stream_emits_cart_event(monkeypatch))


async def _test_chat_stream_emits_cart_event(monkeypatch):
    conversation_id = uuid4().hex
    cart = {
        "conversation_id": conversation_id,
        "items": [_product("p-1") | {"quantity": 1}],
        "total_quantity": 1,
        "total_price": 99.0,
    }

    async def fake_run_turn(conv_id: str, user_message: str):
        yield CartEvent(cart | {"conversation_id": conv_id})
        yield TokenEvent("已加入购物车。")

    monkeypatch.setattr(main, "run_turn", fake_run_turn)

    async with _client() as client:
        response = await client.post(
            "/api/chat",
            json={"conversation_id": conversation_id, "message": "加购"},
        )

    assert response.status_code == 200
    assert "event: cart" in response.text
    assert '"total_quantity": 1' in response.text
    assert "event: token" in response.text
    assert "event: done" in response.text


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _product(
    product_id: str,
    *,
    title: str = "测试商品",
    category: str = "测试类目",
    price: float = 99.0,
) -> dict:
    return {
        "product_id": product_id,
        "title": title,
        "brand": "测试品牌",
        "category": category,
        "sub_category": "测试子类目",
        "price": price,
        "image_url": "/assets/test.jpg",
    }
