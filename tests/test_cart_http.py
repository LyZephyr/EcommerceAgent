from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import cart_store  # noqa: E402
from main import app  # noqa: E402


def test_cart_item_lifecycle():
    asyncio.run(_test_cart_item_lifecycle())


async def _test_cart_item_lifecycle():
    conversation_id = uuid4().hex
    cart_store.record_recent_product(conversation_id, _product("p-1", price=19.9))

    async with _client() as client:
        added = await client.post(
            "/api/cart/items",
            json={
                "conversation_id": conversation_id,
                "product_id": "p-1",
                "quantity": 2,
            },
        )

        assert added.status_code == 200
        assert added.json()["items"][0]["quantity"] == 2
        assert added.json()["total_quantity"] == 2
        assert added.json()["total_price"] == 39.8

        added_again = await client.post(
            "/api/cart/items",
            json={
                "conversation_id": conversation_id,
                "product_id": "p-1",
                "quantity": 1,
            },
        )

        assert added_again.status_code == 200
        assert added_again.json()["items"][0]["quantity"] == 3
        assert added_again.json()["total_quantity"] == 3

        updated = await client.patch(
            "/api/cart/items/p-1",
            json={"conversation_id": conversation_id, "quantity": 1},
        )

        assert updated.status_code == 200
        assert updated.json()["items"][0]["quantity"] == 1
        assert updated.json()["total_quantity"] == 1

        deleted = await client.delete(
            "/api/cart/items/p-1",
            params={"conversation_id": conversation_id},
        )

        assert deleted.status_code == 200
        assert deleted.json()["items"] == []
        assert deleted.json()["total_quantity"] == 0

        cart_store.record_recent_product(conversation_id, _product("p-1", price=19.9))
        await client.post(
            "/api/cart/items",
            json={"conversation_id": conversation_id, "product_id": "p-1"},
        )
        cleared = await client.delete(
            "/api/cart",
            params={"conversation_id": conversation_id},
        )

        assert cleared.status_code == 200
        assert cleared.json()["items"] == []
        assert cleared.json()["total_price"] == 0


def test_cart_isolated_by_conversation_id():
    asyncio.run(_test_cart_isolated_by_conversation_id())


async def _test_cart_isolated_by_conversation_id():
    first_conversation = uuid4().hex
    second_conversation = uuid4().hex
    cart_store.record_recent_product(first_conversation, _product("p-1", price=10))
    cart_store.record_recent_product(second_conversation, _product("p-2", price=20))

    async with _client() as client:
        first_response = await client.post(
            "/api/cart/items",
            json={
                "conversation_id": first_conversation,
                "product_id": "p-1",
            },
        )
        second_response = await client.post(
            "/api/cart/items",
            json={
                "conversation_id": second_conversation,
                "product_id": "p-2",
                "quantity": 2,
            },
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        first_cart = await client.get(
            "/api/cart",
            params={"conversation_id": first_conversation},
        )
        second_cart = await client.get(
            "/api/cart",
            params={"conversation_id": second_conversation},
        )

        assert [item["product_id"] for item in first_cart.json()["items"]] == ["p-1"]
        assert first_cart.json()["total_quantity"] == 1
        assert [item["product_id"] for item in second_cart.json()["items"]] == ["p-2"]
        assert second_cart.json()["total_quantity"] == 2


def test_add_rejects_product_outside_recent_pool():
    asyncio.run(_test_add_rejects_product_outside_recent_pool())


async def _test_add_rejects_product_outside_recent_pool():
    conversation_id = uuid4().hex
    cart_store.record_recent_product("other-" + conversation_id, _product("p-1"))

    async with _client() as client:
        response = await client.post(
            "/api/cart/items",
            json={
                "conversation_id": conversation_id,
                "product_id": "p-1",
            },
        )

        assert response.status_code == 404
        cart = await client.get(
            "/api/cart",
            params={"conversation_id": conversation_id},
        )
        assert cart.json()["items"] == []


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _product(product_id: str, price: float = 99.0) -> dict:
    return {
        "product_id": product_id,
        "title": "测试商品",
        "brand": "测试品牌",
        "category": "测试类目",
        "sub_category": "测试子类目",
        "price": price,
        "image_url": "/assets/test.jpg",
    }
