"""ChromaDB 后台增量同步。

MySQL 是商品权威源；本模块只让语义索引周期性追上 MySQL 的
embedding_text、description 和稳定 metadata。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import datetime

import chromadb

import product_store
from config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR
from embedding import get_embedding_function
from ingest import product_to_chroma_metadata

SYNC_STATE_NAME = "chroma_products"
SYNC_INTERVAL_SECONDS = 180
_INITIAL_SYNC_AT = datetime(1970, 1, 1)

logger = logging.getLogger(__name__)


def sync_once() -> dict:
    """执行一轮 MySQL -> ChromaDB 增量同步，返回统计信息。"""
    started_at = time.monotonic()
    product_store.initialize_database()
    last_sync_at = product_store.get_sync_state(SYNC_STATE_NAME) or _INITIAL_SYNC_AT
    changed_products = product_store.get_products_updated_after(last_sync_at)

    active_products = [
        product
        for product in changed_products
        if product.get("is_active") and int(product.get("stock") or 0) > 0
    ]
    inactive_product_ids = [
        product["product_id"]
        for product in changed_products
        if not product.get("is_active")
    ]

    collection = _get_collection()
    upsert_count = _upsert_products(collection, active_products)
    delete_count = _delete_products(collection, inactive_product_ids)

    if changed_products:
        product_store.set_sync_state(
            SYNC_STATE_NAME,
            max(product["updated_at"] for product in changed_products),
        )

    elapsed_seconds = round(time.monotonic() - started_at, 3)
    stats = {
        "scanned": len(changed_products),
        "upserted": upsert_count,
        "deleted": delete_count,
        "elapsed_seconds": elapsed_seconds,
        "last_sync_at": (
            max(product["updated_at"] for product in changed_products).isoformat()
            if changed_products
            else last_sync_at.isoformat()
        ),
    }
    logger.info(
        "Chroma sync scanned=%s upserted=%s deleted=%s elapsed=%ss",
        stats["scanned"],
        stats["upserted"],
        stats["deleted"],
        stats["elapsed_seconds"],
    )
    return stats


async def run_periodic_sync(
    interval_seconds: int = SYNC_INTERVAL_SECONDS,
    *,
    max_runs: int | None = None,
) -> None:
    run_count = 0
    while True:
        try:
            await asyncio.to_thread(sync_once)
        except Exception:
            logger.exception("ChromaDB 后台同步失败，将在下一轮重试。")
        run_count += 1
        if max_runs is not None and run_count >= max_runs:
            return
        await asyncio.sleep(interval_seconds)


def _get_collection():
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    return client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"description": "Ecommerce product RAG collection"},
    )


def _upsert_products(collection, products: list[dict]) -> int:
    if not products:
        return 0

    embedding_function = get_embedding_function()
    embedding_texts = [product["embedding_text"] for product in products]
    collection.upsert(
        ids=[product["product_id"] for product in products],
        embeddings=embedding_function(embedding_texts),
        documents=[product["description"] for product in products],
        metadatas=[product_to_chroma_metadata(product) for product in products],
    )
    return len(products)


def _delete_products(collection, product_ids: list[str]) -> int:
    if not product_ids:
        return 0
    collection.delete(ids=product_ids)
    return len(product_ids)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="手动执行 MySQL 到 ChromaDB 的增量同步")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="持续按 3 分钟间隔执行；默认只执行一次。",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    if args.loop:
        asyncio.run(run_periodic_sync())
    else:
        print(sync_once())
