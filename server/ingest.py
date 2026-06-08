"""数据导入脚本：读取商品 JSON，构建 embedding 文本与完整文档后写入 ChromaDB。"""

from __future__ import annotations

import json
from pathlib import Path

import chromadb

from config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, DATASET_DIR
from embedding import get_embedding_function

_FAQ_MAX_ITEMS = 5
_FAQ_TRUNCATE_LEN = 30
_REVIEW_MAX_ITEMS = 5
_REVIEW_TRUNCATE_LEN = 50


def load_products(dataset_dir: str) -> list[dict]:
    """扫描 dataset_dir 下所有类目的 JSON 文件，返回商品列表。"""
    root = Path(dataset_dir)
    products: list[dict] = []
    for path in sorted(root.glob("*/data/*.json")):
        product = json.loads(path.read_text(encoding="utf-8"))
        product["_category_dir"] = path.parent.parent.name
        product["_source_path"] = str(path)
        products.append(product)
    return products


def build_embedding_text(product: dict) -> str:
    """为商品构建用于向量化的紧凑文本，控制在 512 token 以内。

    包含：标题 + 品牌 + 类目 + 价格 + 卖点 + FAQ 问题摘要 + 评价摘要。
    """
    knowledge = product.get("rag_knowledge") or {}
    parts = [
        _build_prefix(product),
        f"价格：{product.get('base_price', '')}元",
    ]

    marketing = knowledge.get("marketing_description", "")
    if marketing:
        parts.append(f"卖点：{marketing}")

    faq_items = knowledge.get("official_faq", [])
    if faq_items:
        faq_lines = [
            f"问：{item.get('question', '')[:_FAQ_TRUNCATE_LEN]}"
            for item in faq_items[:_FAQ_MAX_ITEMS]
        ]
        parts.append("官方问答：" + " ".join(faq_lines))

    reviews = knowledge.get("user_reviews", [])
    if reviews:
        review_lines = [
            r.get("content", "")[:_REVIEW_TRUNCATE_LEN]
            for r in reviews[:_REVIEW_MAX_ITEMS]
        ]
        parts.append("用户评价：" + " ".join(review_lines))

    return "\n".join(parts)


def build_full_document(product: dict) -> str:
    """构建完整商品文档，存入 ChromaDB documents 字段供 LLM 阅读。"""
    knowledge = product.get("rag_knowledge") or {}
    sections = [
        f"商品ID：{product['product_id']}",
        f"标题：{product['title']}",
        f"品牌：{product.get('brand', '')}",
        f"类目：{product.get('category', '')} / {product.get('sub_category', '')}",
        f"基础价格：{product.get('base_price', '')}元",
    ]

    marketing = knowledge.get("marketing_description", "")
    if marketing:
        sections.append(f"卖点与使用建议：{marketing}")

    sku_text = _build_sku_text(product)
    if sku_text:
        sections.append(f"SKU：{sku_text}")

    faq_items = knowledge.get("official_faq", [])
    if faq_items:
        faq_lines = [f"问：{item.get('question', '')} 答：{item.get('answer', '')}" for item in faq_items]
        sections.append("官方问答：" + "\n".join(faq_lines))

    reviews = knowledge.get("user_reviews", [])
    if reviews:
        review_lines = [
            f"{r.get('nickname', '用户')}评分{r.get('rating', '')}：{r.get('content', '')}"
            for r in reviews
        ]
        sections.append("用户评价：" + "\n".join(review_lines))

    return "\n".join(sections)


def ingest(dataset_dir: str | None = None):
    """主入口：加载数据 → 构建 embedding 文本 → 写入 ChromaDB。"""
    products = load_products(dataset_dir or DATASET_DIR)
    if not products:
        raise RuntimeError(f"未在数据集目录中找到商品 JSON：{dataset_dir or DATASET_DIR}")

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    existing_names = {collection.name for collection in client.list_collections()}
    if CHROMA_COLLECTION_NAME in existing_names:
        client.delete_collection(CHROMA_COLLECTION_NAME)

    ef = get_embedding_function()
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=ef,
        metadata={"description": "Ecommerce product RAG collection"},
    )

    all_ids: list[str] = []
    all_embedding_texts: list[str] = []
    all_documents: list[str] = []
    all_metadatas: list[dict] = []

    for product in products:
        pid = product["product_id"]
        all_ids.append(pid)
        all_embedding_texts.append(build_embedding_text(product))
        all_documents.append(build_full_document(product))
        all_metadatas.append(_metadata(product))

    embeddings = ef(all_embedding_texts)
    collection.add(
        ids=all_ids,
        embeddings=embeddings,
        documents=all_documents,
        metadatas=all_metadatas,
    )
    print(f"已导入 {len(products)} 个商品到 ChromaDB collection：{CHROMA_COLLECTION_NAME}")


def _build_prefix(product: dict) -> str:
    return (
        f"商品：{product['title']}，"
        f"品牌：{product.get('brand', '')}，"
        f"类目：{product.get('category', '')}/{product.get('sub_category', '')}"
    )


def _build_sku_text(product: dict) -> str:
    sku_lines = []
    for sku in product.get("skus", []):
        properties = "，".join(f"{k}：{v}" for k, v in sku.get("properties", {}).items())
        sku_lines.append(f"{properties}，价格：{sku.get('price')}元")
    return "；".join(sku_lines)


def _metadata(product: dict) -> dict:
    prices = [sku["price"] for sku in product.get("skus", []) if "price" in sku]
    price = float(product.get("base_price") or min(prices))
    return {
        "product_id": product["product_id"],
        "title": product["title"],
        "brand": product.get("brand", ""),
        "category": product.get("category", ""),
        "sub_category": product.get("sub_category", ""),
        "price": price,
        "min_price": float(min(prices)) if prices else price,
        "max_price": float(max(prices)) if prices else price,
        "image_url": _image_url(product),
        "source_path": product.get("_source_path", ""),
    }


def _image_url(product: dict) -> str:
    category_dir = product.get("_category_dir", "")
    product_id = product["product_id"]
    return f"/assets/{category_dir}/images/{product_id}_live.jpg"


if __name__ == "__main__":
    ingest()
