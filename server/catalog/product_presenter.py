"""商品卡片与详情页的公开字段派生逻辑。"""

from __future__ import annotations

import json
import re


def loads_raw_payload(product: dict) -> dict:
    raw_payload = product.get("raw_payload")
    if not raw_payload:
        return {}
    return json.loads(raw_payload)


def product_availability(product: dict) -> tuple[str, str | None]:
    stock = int(product.get("stock") or 0)
    if not product.get("is_active"):
        return "inactive", "商品已下架"
    if stock <= 0:
        return "out_of_stock", "商品库存不足"
    if stock <= 3:
        return "low_stock", None
    return "in_stock", None


def landing_url(product: dict) -> str | None:
    raw_payload = loads_raw_payload(product)
    value = raw_payload.get("landing_url") or raw_payload.get("url")
    return str(value) if value else None


def highlights_from_product(product: dict) -> list[str]:
    raw_payload = loads_raw_payload(product)
    knowledge = raw_payload.get("rag_knowledge") or {}
    highlights = raw_payload.get("highlights")
    if isinstance(highlights, list):
        return [str(item).strip() for item in highlights[:4] if str(item).strip()]

    marketing = str(knowledge.get("marketing_description") or "")
    return _split_sentences(marketing)[:4]


def specs_from_raw_payload(raw_payload: dict) -> list[dict[str, str]]:
    specs_by_name: dict[str, list[str]] = {}
    for sku in raw_payload.get("skus") or []:
        properties = sku.get("properties") or {}
        for name, value in properties.items():
            if value is None:
                continue
            text_value = str(value).strip()
            if not text_value:
                continue
            values = specs_by_name.setdefault(str(name), [])
            if text_value not in values:
                values.append(text_value)
    return [
        {"name": name, "value": " / ".join(values)}
        for name, values in specs_by_name.items()
        if values
    ]


def faq_from_raw_payload(raw_payload: dict) -> list[dict[str, str]]:
    knowledge = raw_payload.get("rag_knowledge") or {}
    faq_items = knowledge.get("official_faq") or []
    return [
        {
            "question": str(item.get("question") or "").strip(),
            "answer": str(item.get("answer") or "").strip(),
        }
        for item in faq_items[:5]
        if str(item.get("question") or "").strip()
        and str(item.get("answer") or "").strip()
    ]


def review_summary_from_raw_payload(reviews: list[dict]) -> dict:
    ratings = [
        float(review["rating"])
        for review in reviews
        if isinstance(review, dict) and review.get("rating") is not None
    ]
    average_rating = round(sum(ratings) / len(ratings), 1) if ratings else None
    highlights = [
        str(review.get("content") or "").strip()
        for review in reviews[:3]
        if isinstance(review, dict) and str(review.get("content") or "").strip()
    ]
    return {
        "average_rating": average_rating,
        "total_count": len(reviews),
        "highlights": highlights,
    }


def product_card_payload(product: dict, *, group_label: str | None = None) -> dict:
    """构造聊天商品卡片和详情页共用的公开商品字段。"""
    stock_status, unavailable_reason = product_availability(product)
    return {
        "product_id": str(product["product_id"]),
        "title": str(product["title"]),
        "brand": product.get("brand"),
        "category": str(product["category"]),
        "sub_category": product.get("sub_category"),
        "price": float(product["price"]),
        "image_url": product.get("image_url"),
        "stock": int(product.get("stock") or 0),
        "detail_url": f"/api/products/{product['product_id']}",
        "landing_url": landing_url(product),
        "highlights": highlights_from_product(product),
        "stock_status": stock_status,
        "unavailable_reason": unavailable_reason,
        "group_label": group_label,
    }


def build_product_detail(product: dict) -> dict:
    """从 MySQL 商品快照派生详情页公开字段，不暴露完整 raw_payload。"""
    raw_payload = loads_raw_payload(product)
    knowledge = raw_payload.get("rag_knowledge") or {}
    reviews = knowledge.get("user_reviews") or []
    return product_card_payload(product) | {
        "description": product.get("description") or "",
        "specs": specs_from_raw_payload(raw_payload),
        "faq": faq_from_raw_payload(raw_payload),
        "review_summary": review_summary_from_raw_payload(reviews),
    }


def _split_sentences(text: str) -> list[str]:
    parts = [
        part.strip()
        for part in re.split(r"[。！？!?；;\n]+", text)
        if part.strip()
    ]
    return [part[:48] for part in parts if part]
