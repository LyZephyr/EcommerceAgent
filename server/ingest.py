"""数据导入脚本：读取商品 JSON，向量化后写入 ChromaDB。"""

from __future__ import annotations

import json
from pathlib import Path

import chromadb

from config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, DATASET_DIR
from embedding import get_embedding_function


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


def build_document(product: dict) -> str:
    """将商品结构化数据拼接为适合向量化的文本 chunk。"""
    knowledge = product.get("rag_knowledge") or {}
    sections = [
        f"商品ID：{product['product_id']}",
        f"标题：{product['title']}",
        f"品牌：{product.get('brand', '')}",
        f"类目：{product.get('category', '')} / {product.get('sub_category', '')}",
        f"基础价格：{product.get('base_price', '')}元",
        f"卖点与使用建议：{knowledge.get('marketing_description', '')}",
    ]

    sku_lines = []
    for sku in product.get("skus", []):
        properties = "，".join(f"{key}：{value}" for key, value in sku.get("properties", {}).items())
        sku_lines.append(f"{properties}，价格：{sku.get('price')}元")
    if sku_lines:
        sections.append("SKU：" + "；".join(sku_lines))

    faq_lines = []
    for item in knowledge.get("official_faq", []):
        faq_lines.append(f"问：{item.get('question', '')} 答：{item.get('answer', '')}")
    if faq_lines:
        sections.append("官方问答：" + "\n".join(faq_lines))

    review_lines = []
    for review in knowledge.get("user_reviews", []):
        review_lines.append(
            f"{review.get('nickname', '用户')}评分{review.get('rating', '')}：{review.get('content', '')}"
        )
    if review_lines:
        sections.append("用户评价：" + "\n".join(review_lines))

    return "\n".join(section for section in sections if section)


def ingest(dataset_dir: str | None = None):
    """主入口：加载数据 → embedding → 写入 ChromaDB。"""
    products = load_products(dataset_dir or DATASET_DIR)
    if not products:
        raise RuntimeError(f"未在数据集目录中找到商品 JSON：{dataset_dir or DATASET_DIR}")

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    existing_names = {collection.name for collection in client.list_collections()}
    if CHROMA_COLLECTION_NAME in existing_names:
        client.delete_collection(CHROMA_COLLECTION_NAME)

    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"description": "Ecommerce product RAG collection"},
    )

    documents = [build_document(product) for product in products]
    collection.add(
        ids=[product["product_id"] for product in products],
        documents=documents,
        metadatas=[_metadata(product) for product in products],
    )
    print(f"已导入 {len(products)} 个商品到 ChromaDB collection：{CHROMA_COLLECTION_NAME}")


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
