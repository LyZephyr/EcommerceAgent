"""检索候选商品格式化与分组辅助。"""

from __future__ import annotations

import json


def flatten_candidate_groups(candidate_groups: list[dict]) -> list[dict]:
    candidates = []
    seen_ids = set()
    for group in candidate_groups:
        for product in group.get("products", []):
            product_id = product["product_id"]
            if product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            candidates.append(product)
    return candidates


def candidate_group_product_ids(candidate_groups: list[dict]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for group in candidate_groups:
        label = (group.get("label") or "").strip()
        if not label:
            continue
        grouped.setdefault(label, set()).update(
            product["product_id"]
            for product in group.get("products", [])
            if product.get("product_id")
        )
    return grouped


def recommend_group_context(
    candidate_groups: list[dict],
) -> tuple[dict[str, set[str]], bool]:
    group_product_ids = candidate_group_product_ids(candidate_groups)
    require_group = len(group_product_ids) > 1
    return group_product_ids, require_group


def format_candidate_groups(candidate_groups: list[dict]) -> str:
    """完整格式，用于当前轮次的 LLM 生成。"""
    groups = [
        {
            "label": group.get("label"),
            "search_query": group.get("search_query"),
            "products": [
                {
                    "product_id": p.get("product_id"),
                    "title": p.get("title"),
                    "brand": p.get("brand"),
                    "category": p.get("category"),
                    "sub_category": p.get("sub_category"),
                    "price": p.get("price"),
                    "stock": p.get("stock"),
                    "image_url": p.get("image_url"),
                    "document": p.get("document"),
                }
                for p in group.get("products", [])
            ],
        }
        for group in candidate_groups
    ]
    return json.dumps(groups, ensure_ascii=False, indent=2)


def format_candidate_groups_compact(candidate_groups: list[dict]) -> str:
    """紧凑格式，存入历史上下文，不含完整 document。"""
    groups = [
        {
            "label": group.get("label"),
            "products": [
                {
                    "product_id": p.get("product_id"),
                    "title": p.get("title"),
                    "brand": p.get("brand"),
                    "category": p.get("category"),
                    "price": p.get("price"),
                    "stock": p.get("stock"),
                }
                for p in group.get("products", [])
            ],
        }
        for group in candidate_groups
    ]
    return json.dumps(groups, ensure_ascii=False)
