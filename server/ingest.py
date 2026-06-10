"""ChromaDB 索引构建脚本。

商品数据的权威源是 MySQL。本模块仍保留数据集 JSON 解析和商品文本构建
函数，供 product_store 启动加载数据集时复用；ChromaDB ingest 本身只读取
MySQL 中的上架商品。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import chromadb

from config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR
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

    包含：标题 + 品牌 + 类目 + SKU 属性摘要 + 卖点 + FAQ 问题摘要 + 评价摘要。
    """
    knowledge = product.get("rag_knowledge") or {}
    parts = [_build_prefix(product)]

    sku_properties = _build_sku_properties_summary(product)
    if sku_properties:
        parts.append(f"SKU属性：{sku_properties}")

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
    """构建完整商品文档，存入 ChromaDB documents 字段供 LLM 阅读。

    价格、库存、上下架等易变字段不写入文档，线上展示和 LLM 可引用的
    关键状态由检索后 MySQL 实时补全提供。
    """
    knowledge = product.get("rag_knowledge") or {}
    sections = [
        f"商品ID：{product['product_id']}",
        f"标题：{product['title']}",
        f"品牌：{product.get('brand', '')}",
        f"类目：{product.get('category', '')} / {product.get('sub_category', '')}",
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


def ingest(dataset_dir: str | None = None, *, reset: bool = True) -> int:
    """从 MySQL 上架商品构建或更新 ChromaDB 索引。

    Args:
        dataset_dir: 可选。传入时先把该数据集 upsert 到 MySQL，再从 MySQL
            读取上架商品写入 ChromaDB。索引写入始终以 MySQL 查询结果为准。
        reset: True 时清空 collection 后重建；False 时对现有 collection
            执行 upsert。

    Returns:
        写入 ChromaDB 的上架商品数量。
    """
    from product_store import list_active_products, load_dataset_to_mysql

    if dataset_dir is not None:
        load_dataset_to_mysql(dataset_dir)

    products = list_active_products()
    if not products:
        raise RuntimeError("MySQL products 表中没有上架商品，无法构建 ChromaDB 索引。")

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    existing_names = {collection.name for collection in client.list_collections()}
    if reset and CHROMA_COLLECTION_NAME in existing_names:
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
        all_embedding_texts.append(product["embedding_text"])
        all_documents.append(product["description"])
        all_metadatas.append(product_to_chroma_metadata(product))

    embeddings = ef(all_embedding_texts)
    collection.upsert(
        ids=all_ids,
        embeddings=embeddings,
        documents=all_documents,
        metadatas=all_metadatas,
    )
    action = "重建" if reset else "更新"
    print(f"已从 MySQL {action} {len(products)} 个上架商品到 ChromaDB collection：{CHROMA_COLLECTION_NAME}")
    return len(products)


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
        if properties:
            sku_lines.append(properties)
    return "；".join(sku_lines)


def _build_sku_properties_summary(product: dict) -> str:
    values_by_name: dict[str, list[str]] = {}
    for sku in product.get("skus", []):
        for name, value in sku.get("properties", {}).items():
            if not value:
                continue
            text_value = str(value)
            values = values_by_name.setdefault(name, [])
            if text_value not in values:
                values.append(text_value)

    return "，".join(
        f"{name}：{'/'.join(values)}"
        for name, values in values_by_name.items()
        if values
    )


def product_to_chroma_metadata(product: dict) -> dict:
    return {
        "product_id": product["product_id"],
        "title": product["title"],
        "brand": product.get("brand", ""),
        "category": product.get("category", ""),
        "sub_category": product.get("sub_category", ""),
        "image_url": product.get("image_url") or _image_url(product),
    }


def _image_url(product: dict) -> str:
    category_dir = product.get("_category_dir", "")
    product_id = product["product_id"]
    return f"/assets/{category_dir}/images/{product_id}_live.jpg"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从 MySQL 构建 ChromaDB 商品索引")
    parser.add_argument(
        "--dataset-dir",
        default=None,
        help="可选：先把指定数据集目录 upsert 到 MySQL，再基于 MySQL 构建索引",
    )
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="不清空 collection，直接 upsert 更新现有 ChromaDB 记录",
    )
    args = parser.parse_args()
    ingest(args.dataset_dir, reset=not args.upsert)
