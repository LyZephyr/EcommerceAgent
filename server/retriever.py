"""RAG 检索模块：基于用户 query 和结构化意图从 ChromaDB 中检索相关商品。"""

from __future__ import annotations

import re

import chromadb

from config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, TOP_K
from embedding import get_embedding_function

_VECTOR_WEIGHT = 0.75
_MUST_TERM_WEIGHT = 0.25
_EXCLUDE_PENALTY_BASE = 0.30
_NEGATION_PREFIXES = ("不含", "无", "未添加", "不添加", "没有", "0", "零")

_chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)


def retrieve(query: str, top_k: int = 5, intent: dict | None = None) -> list[dict]:
    """对 query 做 embedding，结合意图的 metadata filter 检索，返回 Top-K 商品。"""
    collection = _chroma_client.get_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=get_embedding_function(),
    )
    count = collection.count()
    if count == 0:
        raise RuntimeError("商品向量库为空，请先运行 `python ingest.py` 导入数据。")

    limit = min(top_k or TOP_K, count)
    candidate_count = min(max(limit * 6, 30), count)

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

    if not result["ids"][0] and where_filter:
        result = collection.query(
            query_texts=[search_text],
            n_results=candidate_count,
            include=["documents", "metadatas", "distances"],
        )

    products = []
    for chunk_id, document, metadata, distance in zip(
        result["ids"][0],
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
        strict=True,
    ):
        product = dict(metadata)
        product["product_id"] = str(metadata.get("product_id") or chunk_id)
        product["document"] = document
        product["distance"] = float(distance)
        products.append(product)

    return _rerank(products, intent)[:limit]


def _build_where_filter(intent: dict) -> dict | None:
    conditions = []

    category = intent.get("category")
    if category:
        conditions.append({"category": {"$eq": category}})

    min_price = intent.get("min_price")
    if min_price is not None:
        conditions.append({"max_price": {"$gte": float(min_price)}})

    max_price = intent.get("max_price")
    if max_price is not None:
        conditions.append({"min_price": {"$lte": float(max_price)}})

    exclude_brands = intent.get("exclude_brands") or []
    if exclude_brands:
        conditions.append({"brand": {"$nin": exclude_brands}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _rerank(products: list[dict], intent: dict | None = None) -> list[dict]:
    if not products:
        return []

    min_distance = min(product["distance"] for product in products)
    max_distance = max(product["distance"] for product in products)
    distance_span = max_distance - min_distance
    must_have_terms = _string_list(intent.get("must_have_terms")) if intent else []
    exclude_terms = _string_list(intent.get("exclude_terms")) if intent else []

    for product in products:
        if distance_span:
            vector_score = 1.0 - ((product["distance"] - min_distance) / distance_span)
        else:
            vector_score = 1.0

        must_score = _term_match_ratio(must_have_terms, product)
        violation_penalty = _constraint_violation_penalty(exclude_terms, product)
        product["rerank_score"] = (
            _VECTOR_WEIGHT * vector_score
            + _MUST_TERM_WEIGHT * must_score
            - violation_penalty
        )

    return sorted(products, key=lambda product: (product["rerank_score"], -product["distance"]), reverse=True)


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _term_match_ratio(terms: list[str], product: dict) -> float:
    if not terms:
        return 0.0

    haystack = _normalized_text(
        " ".join(
            str(product.get(key, ""))
            for key in ("title", "brand", "category", "sub_category", "document")
        )
    )
    hit_count = sum(1 for term in terms if _normalized_text(term) in haystack)
    return hit_count / len(terms)


def _constraint_violation_penalty(terms: list[str], product: dict) -> float:
    terms = _exclude_terms(terms)
    if not terms:
        return 0.0

    searchable_text = _normalized_text(
        " ".join(
            str(product.get(key, ""))
            for key in ("title", "brand", "sub_category", "category", "document")
        )
    )

    hit_count = sum(
        1 for term in terms
        if _has_unprotected_match(searchable_text, _normalized_text(term))
    )

    if hit_count == 0:
        return 0.0
    return sum(_EXCLUDE_PENALTY_BASE ** i for i in range(1, hit_count + 1))


def _exclude_terms(terms: list[str]) -> list[str]:
    return [term for term in terms if _is_valid_exclude_term(term)]


def _is_valid_exclude_term(term: str) -> bool:
    normalized = _normalized_text(term)
    if not normalized:
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]", normalized):
        return False
    return len(normalized) >= 2


def _has_unprotected_match(text: str, term: str) -> bool:
    start = 0
    while True:
        index = text.find(term, start)
        if index == -1:
            return False
        if not _has_negation_prefix(text, index, term):
            return True
        start = index + len(term)


def _has_negation_prefix(text: str, term_index: int, term: str) -> bool:
    if term.startswith("含") and term_index > 0 and text[term_index - 1] == "不":
        return True
    prefix_window = text[max(0, term_index - 8) : term_index]
    return any(prefix in prefix_window for prefix in _NEGATION_PREFIXES)


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())
