"""检索候选商品格式化与分组辅助。"""

from __future__ import annotations

import json
from typing import Any

from agent.contracts import CandidateGroup


def _group_label(group: CandidateGroup | dict[str, Any]) -> str:
    if isinstance(group, CandidateGroup):
        return (group.label or "").strip()
    return (group.get("label") or "").strip()


def _group_search_query(group: CandidateGroup | dict[str, Any]) -> str | None:
    if isinstance(group, CandidateGroup):
        return group.search_query
    return group.get("search_query")


def _group_products(group: CandidateGroup | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(group, CandidateGroup):
        return [product.to_dict() for product in group.products]
    return group.get("products", [])


def flatten_candidate_groups(candidate_groups: list[CandidateGroup | dict]) -> list[dict]:
    candidates = []
    seen_ids = set()
    for group in candidate_groups:
        for product in _group_products(group):
            product_id = product["product_id"]
            if product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            candidates.append(product)
    return candidates


def candidate_group_product_ids(
    candidate_groups: list[CandidateGroup | dict],
) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for group in candidate_groups:
        label = _group_label(group)
        if not label:
            continue
        grouped.setdefault(label, set()).update(
            product["product_id"]
            for product in _group_products(group)
            if product.get("product_id")
        )
    return grouped


def recommend_group_context(
    candidate_groups: list[CandidateGroup | dict],
) -> tuple[dict[str, set[str]], bool]:
    group_product_ids = candidate_group_product_ids(candidate_groups)
    require_group = len(group_product_ids) > 1
    return group_product_ids, require_group


def format_candidate_groups(candidate_groups: list[CandidateGroup | dict]) -> str:
    """完整格式，用于当前轮次 LLM 生成及会话历史持久化。"""
    groups = [
        {
            "label": _group_label(group) or None,
            "search_query": _group_search_query(group),
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
                for p in _group_products(group)
            ],
        }
        for group in candidate_groups
    ]
    return json.dumps(groups, ensure_ascii=False, indent=2)
