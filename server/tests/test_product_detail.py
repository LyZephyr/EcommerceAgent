from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import product_store
from api.products import get_product_detail
from catalog import product_presenter


def test_get_product_detail_returns_public_detail_fields(monkeypatch) -> None:
    monkeypatch.setattr(product_store, "get_product_by_id", lambda product_id: _product())

    detail = product_store.get_product_detail("p1")

    assert detail is not None
    assert detail["product_id"] == "p1"
    assert detail["detail_url"] == "/api/products/p1"
    assert detail["landing_url"] is None
    assert detail["stock_status"] == "low_stock"
    assert detail["unavailable_reason"] is None
    assert detail["highlights"]
    assert detail["specs"] == [{"name": "规格", "value": "250ml / 1L"}]
    assert detail["faq"] == [{"question": "怎么保存？", "answer": "常温保存。"}]
    assert detail["review_summary"]["average_rating"] == 4.5
    assert "raw_payload" not in detail


def test_get_product_detail_returns_none_for_missing_product(monkeypatch) -> None:
    monkeypatch.setattr(product_store, "get_product_by_id", lambda product_id: None)

    assert product_store.get_product_detail("missing") is None


def test_product_detail_endpoint_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(product_store, "get_product_detail", lambda product_id: None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_product_detail("missing"))

    assert exc_info.value.status_code == 404


def test_product_card_payload_marks_inactive_and_out_of_stock() -> None:
    inactive = product_presenter.product_card_payload(_product(is_active=False, stock=8))
    out_of_stock = product_presenter.product_card_payload(_product(stock=0))

    assert inactive["stock_status"] == "inactive"
    assert inactive["unavailable_reason"] == "商品已下架"
    assert out_of_stock["stock_status"] == "out_of_stock"
    assert out_of_stock["unavailable_reason"] == "商品库存不足"


def test_product_card_payload_includes_group_label() -> None:
    card = product_presenter.product_card_payload(_product(), group_label="早餐奶")

    assert card["group_label"] == "早餐奶"
    assert card["detail_url"] == "/api/products/p1"


def _product(*, is_active: bool = True, stock: int = 2) -> dict:
    raw_payload = {
        "product_id": "p1",
        "title": "测试牛奶",
        "skus": [
            {"properties": {"规格": "250ml"}},
            {"properties": {"规格": "1L"}},
        ],
        "rag_knowledge": {
            "marketing_description": "口感清爽。适合早餐。",
            "official_faq": [{"question": "怎么保存？", "answer": "常温保存。"}],
            "user_reviews": [
                {"rating": 5, "content": "味道稳定。"},
                {"rating": 4, "content": "早餐方便。"},
            ],
        },
    }
    return {
        "product_id": "p1",
        "title": "测试牛奶",
        "brand": "测试品牌",
        "category": "食品饮料",
        "sub_category": "牛奶",
        "price": 12.0,
        "stock": stock,
        "is_active": is_active,
        "image_url": "/assets/p1.jpg",
        "description": "商品详情",
        "raw_payload": json.dumps(raw_payload, ensure_ascii=False),
    }
