"""数据导入脚本：读取商品 JSON，按语义分 chunk 向量化后写入 ChromaDB。"""

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


def build_chunks(product: dict) -> list[dict]:
    """为一个商品生成多个语义 chunk，每个 chunk 带商品基本信息前缀。

    返回 list[{"chunk_id": str, "embedding_text": str, "chunk_type": str}]。
    - core: 标题 + 品牌 + 类目 + 价格 + 卖点 + SKU 属性
    - faq: 标题前缀 + 官方问答
    - review: 标题前缀 + 用户评价
    """
    knowledge = product.get("rag_knowledge") or {}
    product_id = product["product_id"]
    prefix = _build_prefix(product)

    chunks = []

    # Chunk 1: 核心卖点（始终存在）
    core_parts = [
        prefix,
        f"价格：{product.get('base_price', '')}元",
    ]
    marketing = knowledge.get("marketing_description", "")
    if marketing:
        core_parts.append(f"卖点：{marketing}")
    sku_text = _build_sku_text(product)
    if sku_text:
        core_parts.append(f"SKU：{sku_text}")
    chunks.append({
        "chunk_id": f"{product_id}__core",
        "embedding_text": "\n".join(core_parts),
        "chunk_type": "core",
    })

    # Chunk 2: FAQ（如果存在）
    faq_items = knowledge.get("official_faq", [])
    if faq_items:
        faq_lines = [f"问：{item.get('question', '')} 答：{item.get('answer', '')}" for item in faq_items]
        chunks.append({
            "chunk_id": f"{product_id}__faq",
            "embedding_text": f"{prefix}\n官方问答：\n" + "\n".join(faq_lines),
            "chunk_type": "faq",
        })

    # Chunk 3: 用户评价（如果存在）
    reviews = knowledge.get("user_reviews", [])
    if reviews:
        review_lines = [
            f"{r.get('nickname', '用户')}评分{r.get('rating', '')}：{r.get('content', '')}"
            for r in reviews
        ]
        chunks.append({
            "chunk_id": f"{product_id}__review",
            "embedding_text": f"{prefix}\n用户评价：\n" + "\n".join(review_lines),
            "chunk_type": "review",
        })

    return chunks


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
    """主入口：加载数据 → 分 chunk → embedding → 写入 ChromaDB。"""
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

    full_docs_map = {p["product_id"]: build_full_document(p) for p in products}
    metadata_map = {p["product_id"]: _metadata(p) for p in products}

    all_ids: list[str] = []
    all_embedding_texts: list[str] = []
    all_documents: list[str] = []
    all_metadatas: list[dict] = []

    for product in products:
        pid = product["product_id"]
        chunks = build_chunks(product)
        full_doc = full_docs_map[pid]
        meta = metadata_map[pid]

        for chunk in chunks:
            all_ids.append(chunk["chunk_id"])
            all_embedding_texts.append(chunk["embedding_text"])
            all_documents.append(full_doc)
            all_metadatas.append({**meta, "chunk_type": chunk["chunk_type"]})

    embeddings = ef(all_embedding_texts)
    collection.add(
        ids=all_ids,
        embeddings=embeddings,
        documents=all_documents,
        metadatas=all_metadatas,
    )
    print(f"已导入 {len(products)} 个商品（{len(all_ids)} 个 chunk）到 ChromaDB collection：{CHROMA_COLLECTION_NAME}")


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
