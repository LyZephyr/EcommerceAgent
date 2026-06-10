from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import cart_store  # noqa: E402
import product_store  # noqa: E402
from main import app  # noqa: E402


def test_cart_item_lifecycle(monkeypatch):
    _install_product_store(
        monkeypatch,
        {
            "p-1": _product("p-1", price=19.9),
        },
    )
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


def test_cart_isolated_by_conversation_id(monkeypatch):
    _install_product_store(
        monkeypatch,
        {
            "p-1": _product("p-1", price=10),
            "p-2": _product("p-2", price=20),
        },
    )
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


def test_add_uses_latest_mysql_price(monkeypatch):
    _install_product_store(
        monkeypatch,
        {
            "p-1": _product("p-1", price=29.9),
        },
    )
    asyncio.run(_test_add_uses_latest_mysql_price())


async def _test_add_uses_latest_mysql_price():
    conversation_id = uuid4().hex
    cart_store.record_recent_product(conversation_id, _product("p-1", price=19.9))

    async with _client() as client:
        response = await client.post(
            "/api/cart/items",
            json={
                "conversation_id": conversation_id,
                "product_id": "p-1",
                "quantity": 1,
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["items"][0]["price"] == 29.9
    assert body["total_price"] == 29.9
    assert "价格已更新" in body["messages"][0]


def test_get_cart_refreshes_latest_mysql_price(monkeypatch):
    products = {
        "p-1": _product("p-1", price=19.9),
    }
    _install_product_store(monkeypatch, products)
    asyncio.run(_test_get_cart_refreshes_latest_mysql_price(products))


async def _test_get_cart_refreshes_latest_mysql_price(products: dict[str, dict]):
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
        products["p-1"]["price"] = 24.9

        refreshed = await client.get(
            "/api/cart",
            params={"conversation_id": conversation_id},
        )
        refreshed_again = await client.get(
            "/api/cart",
            params={"conversation_id": conversation_id},
        )

    body = refreshed.json()
    assert added.status_code == 200
    assert added.json()["messages"] == []
    assert refreshed.status_code == 200
    assert body["items"][0]["price"] == 24.9
    assert body["total_price"] == 49.8
    assert body["messages"] == [
        "「测试商品」价格已更新：已从 ¥19.90 更新为 ¥24.90。",
    ]
    assert refreshed_again.json()["messages"] == []


def test_get_cart_refreshes_latest_mysql_availability(monkeypatch):
    products = {
        "p-1": _product("p-1", price=19.9),
    }
    _install_product_store(monkeypatch, products)
    asyncio.run(_test_get_cart_refreshes_latest_mysql_availability(products))


async def _test_get_cart_refreshes_latest_mysql_availability(
    products: dict[str, dict],
):
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
        products["p-1"]["stock"] = 0

        out_of_stock = await client.get(
            "/api/cart",
            params={"conversation_id": conversation_id},
        )
        products["p-1"]["stock"] = 5
        products["p-1"]["is_active"] = False

        inactive = await client.get(
            "/api/cart",
            params={"conversation_id": conversation_id},
        )

    assert added.status_code == 200
    assert out_of_stock.status_code == 200
    out_of_stock_body = out_of_stock.json()
    assert out_of_stock_body["items"][0]["product_id"] == "p-1"
    assert out_of_stock_body["items"][0]["stock"] == 0
    assert out_of_stock_body["items"][0]["stock_status"] == "out_of_stock"
    assert out_of_stock_body["items"][0]["unavailable_reason"] == "库存不足"
    assert inactive.status_code == 200
    inactive_body = inactive.json()
    assert inactive_body["items"] == []
    assert inactive_body["messages"] == ["「测试商品」已下架，已从购物车移除。"]


def test_add_rejects_out_of_stock_mysql_product(monkeypatch):
    _install_product_store(
        monkeypatch,
        {
            "p-1": _product("p-1", price=19.9) | {"stock": 0},
        },
    )
    asyncio.run(_test_add_rejects_out_of_stock_mysql_product())


async def _test_add_rejects_out_of_stock_mysql_product():
    conversation_id = uuid4().hex
    cart_store.record_recent_product(conversation_id, _product("p-1", price=19.9))

    async with _client() as client:
        response = await client.post(
            "/api/cart/items",
            json={
                "conversation_id": conversation_id,
                "product_id": "p-1",
                "quantity": 1,
            },
        )
        cart = await client.get(
            "/api/cart",
            params={"conversation_id": conversation_id},
        )

    assert response.status_code == 409
    assert "库存不足" in response.json()["detail"]
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
