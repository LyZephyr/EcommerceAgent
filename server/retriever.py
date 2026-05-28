"""RAG 检索模块：基于用户 query 从 ChromaDB 中检索相关商品。"""

from __future__ import annotations

import re

import chromadb

from config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, TOP_K
from embedding import get_embedding_function


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """对 query 做 embedding，在 ChromaDB 中检索 Top-K 相似商品，返回商品元数据列表。"""
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
    result = collection.query(
        query_texts=[_expand_query(query)],
        n_results=candidate_count,
        include=["documents", "metadatas", "distances"],
    )

    products = []
    ids = result["ids"][0]
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]
    for product_id, document, metadata, distance in zip(ids, documents, metadatas, distances, strict=True):
        product = dict(metadata)
        product["product_id"] = str(product.get("product_id") or product_id)
        product["document"] = document
        product["distance"] = float(distance)
        products.append(product)
    return _rerank(query, products)[:limit]


def _expand_query(query: str) -> str:
    synonyms = []
    synonym_rules = {
        "洗面奶": ["洁面", "洁面乳", "清洁", "泡沫"],
        "油皮": ["控油", "油脂", "清爽", "混合性皮肤"],
        "敏感肌": ["舒缓", "温和", "屏障", "低刺激"],
        "手机": ["智能手机", "全网通", "续航", "拍照"],
        "电脑": ["笔记本", "处理器", "性能", "办公"],
        "耳机": ["降噪", "蓝牙", "音质", "续航"],
        "零食": ["食品", "坚果", "饼干", "礼盒"],
        "礼盒": ["送礼", "独立包装", "坚果", "组合装"],
    }
    for word, expansions in synonym_rules.items():
        if word in query:
            synonyms.extend(expansions)
    return " ".join([query, *synonyms])


def _rerank(query: str, products: list[dict]) -> list[dict]:
    expanded_query = _expand_query(query)
    price_target = _price_target(query)
    return sorted(
        products,
        key=lambda product: (
            _lexical_score(expanded_query, product) + _price_score(price_target, product),
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
        "一": 1,
        "两": 2,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
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
