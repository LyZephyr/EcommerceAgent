"""RAG 检索模块：基于用户 query 和结构化意图从 ChromaDB 中检索相关商品。"""

from __future__ import annotations

import re

import chromadb

from config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, TOP_K
from embedding import get_embedding_function


def retrieve(query: str, top_k: int = 5, intent: dict | None = None) -> list[dict]:
    """对 query 做 embedding，结合意图的 metadata filter 检索，按 product_id 去重后返回 Top-K 商品。"""
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    collection = client.get_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=get_embedding_function(),
    )
    count = collection.count()
    if count == 0:
        raise RuntimeError("商品向量库为空，请先运行 `python ingest.py` 导入数据。")

    limit = min(top_k or TOP_K, count)
    candidate_count = min(max(limit * 10, 30), count)

    search_text = query
    where_filter = None
    if intent:
        search_text = intent.get("rewritten_query") or query
        where_filter = _build_where_filter(intent)

    result = collection.query(
        query_texts=[search_text],
        n_results=candidate_count,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    # 过滤条件过严导致零结果时，去掉 filter 重试
    if not result["ids"][0] and where_filter:
        result = collection.query(
            query_texts=[search_text],
            n_results=candidate_count,
            include=["documents", "metadatas", "distances"],
        )

    best: dict[str, dict] = {}
    ids = result["ids"][0]
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]

    for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances, strict=True):
        pid = str(metadata.get("product_id") or chunk_id.split("__")[0])
        if pid not in best or distance < best[pid]["distance"]:
            product = dict(metadata)
            product["product_id"] = pid
            product["document"] = document
            product["distance"] = float(distance)
            best[pid] = product

    products = list(best.values())
    return _rerank(query, products)[:limit]


def _build_where_filter(intent: dict) -> dict | None:
    conditions = []

    category = intent.get("category")
    if category:
        conditions.append({"category": {"$eq": category}})

    min_price = intent.get("min_price")
    if min_price is not None:
        conditions.append({"price": {"$gte": float(min_price)}})

    max_price = intent.get("max_price")
    if max_price is not None:
        conditions.append({"price": {"$lte": float(max_price)}})

    exclude_brands = intent.get("exclude_brands") or []
    if exclude_brands:
        conditions.append({"brand": {"$nin": exclude_brands}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _rerank(query: str, products: list[dict]) -> list[dict]:
    price_target = _price_target(query)
    return sorted(
        products,
        key=lambda product: (
            _lexical_score(query, product) + _price_score(price_target, product),
            -product["distance"],
        ),
        reverse=True,
    )


def _lexical_score(query: str, product: dict) -> float:
    haystack = " ".join(
        str(product.get(key, ""))
        for key in ("title", "brand", "category", "sub_category", "document")
    ).lower()
    score = 0.0
    for term in _terms(query):
        if term in haystack:
            score += 2.0 if len(term) > 1 else 0.2
    return score


def _terms(text: str) -> set[str]:
    normalized = text.lower()
    terms = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", normalized))
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    terms.update(
        "".join(chinese_chars[index : index + size])
        for size in (2, 3)
        for index in range(max(len(chinese_chars) - size + 1, 0))
    )
    return terms


def _price_target(query: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(万|千|元|块)", query)
    if match:
        value = float(match.group(1))
        unit = match.group(2)
        if unit == "万":
            return value * 10000
        if unit == "千":
            return value * 1000
        return value

    chinese_numbers = {
        "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    match = re.search(r"([一两二三四五六七八九十])\s*(万|千)", query)
    if not match:
        return None
    value = chinese_numbers[match.group(1)]
    return float(value * (10000 if match.group(2) == "万" else 1000))


def _price_score(price_target: float | None, product: dict) -> float:
    if price_target is None:
        return 0.0
    price = float(product.get("price") or 0)
    if price <= 0:
        return 0.0
    difference_ratio = abs(price - price_target) / max(price_target, 1.0)
    return max(0.0, 3.0 * (1.0 - difference_ratio))
