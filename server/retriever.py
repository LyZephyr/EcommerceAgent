"""RAG 检索模块：基于用户 query 和结构化意图从 ChromaDB 中检索相关商品。"""

from __future__ import annotations

import re

import chromadb

import product_store
from config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, TOP_K
from embedding import get_embedding_function

_VECTOR_WEIGHT = 0.7
_MUST_TERM_WEIGHT = 0.3
_EXCLUDE_DOCUMENT_PENALTY_BASE = 0.25
_EXCLUDE_REVIEW_PENALTY_BASE = 0.15
_NEGATION_PREFIXES = ("无", "未", "非", "没", "0", "零", "不")
_USER_REVIEW_SECTION_MARKERS = ("\n用户评价:", "\n用户评价：")

_chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)


def retrieve(query: str, top_k: int = 5, intent: dict | None = None) -> list[dict]:
    """召回 ChromaDB 候选，再用 MySQL 最新商品快照补全和过滤。"""
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

    candidates = []
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
        candidates.append(product)

    ranked_candidates = _rerank(candidates, intent)
    return _hydrate_and_filter_products(ranked_candidates, intent)[:limit]


def _build_where_filter(intent: dict) -> dict | None:
    conditions = []

    category = intent.get("category")
    if category:
        conditions.append({"category": {"$eq": category}})

    exclude_brands = intent.get("exclude_brands") or []
    if exclude_brands:
        conditions.append({"brand": {"$nin": exclude_brands}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _hydrate_and_filter_products(
    candidates: list[dict],
    intent: dict | None = None,
) -> list[dict]:
    if not candidates:
        return []

    candidate_by_id = {candidate["product_id"]: candidate for candidate in candidates}
    mysql_products = product_store.get_products_by_ids(
        [candidate["product_id"] for candidate in candidates]
    )

    products = []
    for mysql_product in mysql_products:
        candidate = candidate_by_id.get(mysql_product["product_id"])
        if not candidate or not _passes_mysql_filters(mysql_product, intent):
            continue
        products.append(_product_from_mysql(mysql_product, candidate))
    return products


def _passes_mysql_filters(product: dict, intent: dict | None = None) -> bool:
    if not product.get("is_active"):
        return False
    if int(product.get("stock") or 0) <= 0:
        return False
    if not intent:
        return True

    category = intent.get("category")
    if category and product.get("category") != category:
        return False

    exclude_brands = _string_list(intent.get("exclude_brands"))
    if _normalized_text(str(product.get("brand") or "")) in {
        _normalized_text(brand) for brand in exclude_brands
    }:
        return False

    min_price = intent.get("min_price")
    if min_price is not None and float(product["price"]) < float(min_price):
        return False

    max_price = intent.get("max_price")
    if max_price is not None and float(product["price"]) > float(max_price):
        return False

    return True


def _product_from_mysql(product: dict, candidate: dict) -> dict:
    price = float(product["price"])
    return {
        "product_id": str(product["product_id"]),
        "title": product["title"],
        "brand": product.get("brand") or "",
        "category": product.get("category") or "",
        "sub_category": product.get("sub_category") or "",
        "price": price,
        "min_price": price,
        "max_price": price,
        "stock": int(product.get("stock") or 0),
        "is_active": bool(product.get("is_active")),
        "image_url": product.get("image_url") or "",
        "document": _document_for_llm(str(product.get("description") or "")),
        "distance": candidate["distance"],
        "rerank_score": candidate.get("rerank_score", 0.0),
    }


def _document_for_llm(document: str) -> str:
    document = re.sub(r"(?m)^基础价格：.*(?:\n|$)", "", document)
    document = re.sub(r"，价格：[^，；\n]+元", "", document)
    return document.strip()


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

    return sorted(
        products,
        key=lambda product: (product["rerank_score"], -product["distance"]),
        reverse=True,
    )


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
    if not terms:
        return 0.0

    product_document, review_document = _split_review_document(str(product.get("document", "")))
    product_text = _normalized_text(
        " ".join(
            str(product.get(key, ""))
            for key in ("title", "brand", "sub_category", "category")
        )
        + " "
        + product_document
    )
    review_text = _normalized_text(review_document)

    product_hit_count = _unprotected_hit_count(terms, product_text)
    review_hit_count = _unprotected_hit_count(terms, review_text)
    return _decayed_penalty(
        product_hit_count,
        _EXCLUDE_DOCUMENT_PENALTY_BASE,
    ) + _decayed_penalty(review_hit_count, _EXCLUDE_REVIEW_PENALTY_BASE)


def _split_review_document(document: str) -> tuple[str, str]:
    for marker_text in _USER_REVIEW_SECTION_MARKERS:
        product_document, marker, review_document = document.partition(marker_text)
        if marker:
            return product_document, review_document
    return document, ""


def _unprotected_hit_count(terms: list[str], text: str) -> int:
    return sum(
        1
        for term in terms
        if _has_unprotected_match(text, _normalized_text(term))
    )


def _decayed_penalty(hit_count: int, base: float) -> float:
    if hit_count == 0:
        return 0.0
    return sum(base ** i for i in range(1, hit_count + 1))


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
