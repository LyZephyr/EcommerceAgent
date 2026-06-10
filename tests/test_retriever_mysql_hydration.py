from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import retriever  # noqa: E402


def test_hydrate_filters_with_mysql_authoritative_fields(monkeypatch):
    candidates = [
        _candidate("p-ok", 0.1),
        _candidate("p-no-stock", 0.2),
        _candidate("p-inactive", 0.3),
        _candidate("p-expensive", 0.4),
        _candidate("p-category", 0.5),
        _candidate("p-brand", 0.6),
        _candidate("p-missing", 0.7),
    ]
    rows_by_id = {
        "p-ok": _mysql_product(
            "p-ok",
            price=99,
            description="商品ID：p-ok\n基础价格：199元\nSKU：颜色：黑，价格：199元\n用户评价：好用",
        ),
        "p-no-stock": _mysql_product("p-no-stock", stock=0),
        "p-inactive": _mysql_product("p-inactive", is_active=False),
        "p-expensive": _mysql_product("p-expensive", price=199),
        "p-category": _mysql_product("p-category", category="食品饮料"),
        "p-brand": _mysql_product("p-brand", brand="排除牌"),
    }

    def fake_get_products_by_ids(product_ids: list[str]) -> list[dict]:
        return [
            rows_by_id[product_id]
            for product_id in product_ids
            if product_id in rows_by_id
        ]

    monkeypatch.setattr(
        retriever.product_store,
        "get_products_by_ids",
        fake_get_products_by_ids,
    )

    products = retriever._hydrate_and_filter_products(
        candidates,
        {
            "category": "数码电子",
            "max_price": 100,
            "exclude_brands": ["排除牌"],
        },
    )

    assert [product["product_id"] for product in products] == ["p-ok"]
    assert products[0]["price"] == 99
    assert products[0]["stock"] == 2
    assert "基础价格" not in products[0]["document"]
    assert "价格：199元" not in products[0]["document"]


def test_chroma_where_filter_does_not_use_stale_price_metadata():
    where_filter = retriever._build_where_filter(
        {
            "category": "数码电子",
            "min_price": 100,
            "max_price": 200,
            "exclude_brands": ["旧品牌"],
        }
    )

    assert where_filter == {
        "$and": [
            {"category": {"$eq": "数码电子"}},
            {"brand": {"$nin": ["旧品牌"]}},
        ]
    }


def _candidate(product_id: str, distance: float) -> dict:
    return {
        "product_id": product_id,
        "title": "旧标题",
        "brand": "旧品牌",
        "category": "旧类目",
        "sub_category": "旧子类目",
        "document": "旧文档",
        "distance": distance,
        "rerank_score": 1.0 - distance,
    }


def _mysql_product(
    product_id: str,
    *,
    price: float = 88,
    stock: int = 2,
    is_active: bool = True,
    brand: str = "权威品牌",
    category: str = "数码电子",
    description: str = "权威文档",
) -> dict:
    return {
        "product_id": product_id,
        "title": f"权威商品 {product_id}",
        "brand": brand,
        "category": category,
        "sub_category": "耳机",
        "price": price,
        "stock": stock,
        "is_active": is_active,
        "image_url": f"/assets/{product_id}.jpg",
        "description": description,
    }
