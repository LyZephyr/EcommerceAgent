from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

import cart_store
import product_store
from api.products import get_product_detail
from main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_health_endpoint() -> None:
    response = asyncio.run(_get("/health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_product_detail_endpoint_returns_detail(monkeypatch) -> None:
    monkeypatch.setattr(
        product_store,
        "get_product_detail",
        lambda product_id: {
            "product_id": product_id,
            "title": "测试牛奶",
            "brand": "测试品牌",
            "category": "食品饮料",
            "sub_category": "牛奶",
            "price": 12.0,
            "image_url": "/assets/p1.jpg",
            "stock": 2,
            "detail_url": f"/api/products/{product_id}",
            "landing_url": None,
            "highlights": ["口感清爽。"],
            "stock_status": "low_stock",
            "unavailable_reason": None,
            "description": "商品详情",
            "specs": [],
            "faq": [],
            "review_summary": {
                "average_rating": None,
                "total_count": 0,
                "highlights": [],
            },
        },
    )

    response = asyncio.run(_get("/api/products/p1"))
    assert response.status_code == 200
    assert response.json()["product_id"] == "p1"


def test_product_detail_endpoint_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(product_store, "get_product_detail", lambda product_id: None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_product_detail("missing"))

    assert exc_info.value.status_code == 404


def test_cart_snapshot_endpoint() -> None:
    conversation_id = uuid4().hex
    response = asyncio.run(_get("/api/cart", params={"conversation_id": conversation_id}))

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total_quantity"] == 0


def test_cart_add_item_endpoint(monkeypatch) -> None:
    conversation_id = uuid4().hex
    product = _product("p-1", price=19.9)
    _install_product_store(monkeypatch, {"p-1": product})
    cart_store.record_recent_product(conversation_id, product)

    response = asyncio.run(
        _post(
            "/api/cart/items",
            json={
                "conversation_id": conversation_id,
                "product_id": "p-1",
                "quantity": 2,
            },
        )
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["quantity"] == 2
    assert response.json()["total_quantity"] == 2


async def _get(path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, **kwargs)


async def _post(path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, **kwargs)


def _install_product_store(monkeypatch, products: dict[str, dict]) -> None:
    def fake_get_product_by_id(product_id: str):
        return products.get(product_id)

    def fake_get_products_by_ids(product_ids: list[str]):
        return [
            products[product_id]
            for product_id in product_ids
            if product_id in products
        ]

    monkeypatch.setattr(product_store, "get_product_by_id", fake_get_product_by_id)
    monkeypatch.setattr(product_store, "get_products_by_ids", fake_get_products_by_ids)


def _product(product_id: str, *, price: float = 12.0) -> dict:
    return {
        "product_id": product_id,
        "title": f"商品 {product_id}",
        "brand": "测试品牌",
        "category": "食品饮料",
        "sub_category": "牛奶",
        "price": price,
        "image_url": "/assets/test.jpg",
        "stock": 3,
        "is_active": True,
        "raw_payload": json.dumps({"product_id": product_id}, ensure_ascii=False),
    }
