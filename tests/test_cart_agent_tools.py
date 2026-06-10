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
import product_store  # noqa: E402
from agent import BlockProductEvent, BlockTextEvent, CartEvent  # noqa: E402
from tools import execute  # noqa: E402


def test_cart_tool_adds_recent_products_by_ids(monkeypatch):
    conversation_id = uuid4().hex
    products = {
        "p-1": _product("p-1", title="第一款"),
        "p-2": _product("p-2", title="第二款"),
    }
    _install_product_store(monkeypatch, products)
    cart_store.record_recent_product(conversation_id, products["p-1"])
    cart_store.record_recent_product(conversation_id, products["p-2"])

    result = execute(
        "add_to_cart",
        {"product_ids": ["p-1", "p-2"], "quantity": 2},
        conversation_id,
    )

    assert result["success"] is True
    assert [item["product_id"] for item in result["cart"]["items"]] == ["p-1", "p-2"]
    assert result["cart"]["items"][0]["quantity"] == 2
    assert result["cart"]["items"][1]["quantity"] == 2
    assert result["cart"]["total_quantity"] == 4


def test_cart_tool_updates_and_removes_by_keyword(monkeypatch):
    conversation_id = uuid4().hex
    product = _product("p-1", title="轻量蓝牙耳机", category="数码电子")
    _install_product_store(monkeypatch, {"p-1": product})
    cart_store.record_recent_product(conversation_id, product)
    execute("add_to_cart", {"product_ids": ["p-1"]}, conversation_id)

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


def test_cart_tool_requires_product_ids(monkeypatch):
    conversation_id = uuid4().hex
    products = {
        "p-1": _product("p-1", title="第一款"),
        "p-2": _product("p-2", title="第二款"),
    }
    _install_product_store(monkeypatch, products)
    cart_store.record_recent_product(conversation_id, products["p-1"])
    cart_store.record_recent_product(conversation_id, products["p-2"])

    result = execute("add_to_cart", {}, conversation_id)

    assert result["success"] is False
    assert "商品 ID" in result["message"]
    assert cart_store.snapshot(conversation_id)["items"] == []


def test_cart_tool_lists_recent_products_newest_first(monkeypatch):
    conversation_id = uuid4().hex
    products = {
        "p-1": _product("p-1", title="早些展示", price=10),
        "p-2": _product("p-2", title="最近展示", price=20),
    }
    _install_product_store(monkeypatch, products)
    cart_store.record_recent_product(conversation_id, products["p-1"])
    cart_store.record_recent_product(conversation_id, products["p-2"])

    result = execute("list_recent_products", {}, conversation_id)

    assert result["success"] is True
    assert [product["product_id"] for product in result["products"]] == ["p-2", "p-1"]
    assert result["products"][0]["displayed_price"] == 20


def test_chat_stream_emits_cart_event(monkeypatch):
    asyncio.run(_test_chat_stream_emits_cart_event(monkeypatch))


def test_chat_stream_emits_block_events_only(monkeypatch):
    asyncio.run(_test_chat_stream_emits_block_events_only(monkeypatch))


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
        yield BlockTextEvent("asst-test", "blk-1", "已加入购物车。")

    monkeypatch.setattr(main, "run_turn", fake_run_turn)

    async with _client() as client:
        response = await client.post(
            "/api/chat",
            json={"conversation_id": conversation_id, "message": "加购"},
        )

    assert response.status_code == 200
    assert "event: cart" in response.text
    assert '"total_quantity": 1' in response.text
    assert "event: block" in response.text
    assert '"type": "text"' in response.text
    assert "event: done" in response.text


async def _test_chat_stream_emits_block_events_only(monkeypatch):
    conversation_id = uuid4().hex
    product = _product("p-1", title="测试牛奶")

    async def fake_run_turn(conv_id: str, user_message: str):
        yield BlockTextEvent("asst-test", "blk-1", "整体建议。")
        yield BlockProductEvent("asst-test", "blk-2", "p-1", product)

    monkeypatch.setattr(main, "run_turn", fake_run_turn)

    async with _client() as client:
        response = await client.post(
            "/api/chat",
            json={
                "conversation_id": conversation_id,
                "message": "推荐",
            },
        )

    assert "event: block" in response.text
    assert '"type": "text"' in response.text
    assert '"type": "product"' in response.text


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
        "stock": 5,
        "is_active": True,
    }


def _install_product_store(monkeypatch, products: dict[str, dict]) -> None:
    def fake_get_product_by_id(product_id: str) -> dict | None:
        product = products.get(product_id)
        return dict(product) if product else None

    def fake_get_products_by_ids(product_ids: list[str]) -> list[dict]:
        return [
            dict(products[product_id])
            for product_id in product_ids
            if product_id in products
        ]

    monkeypatch.setattr(product_store, "get_product_by_id", fake_get_product_by_id)
    monkeypatch.setattr(product_store, "get_products_by_ids", fake_get_products_by_ids)
