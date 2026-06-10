from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import chroma_sync  # noqa: E402


def test_sync_once_upserts_active_products_and_deletes_inactive(monkeypatch, caplog):
    active_updated_at = datetime(2026, 1, 1, 10, 0, 0)
    inactive_updated_at = datetime(2026, 1, 1, 10, 1, 0)
    products = [
        _product("p-active", updated_at=active_updated_at),
        _product(
            "p-inactive",
            updated_at=inactive_updated_at,
            is_active=False,
        ),
    ]
    collection = _FakeCollection()
    sync_state = {}

    monkeypatch.setattr(chroma_sync.product_store, "initialize_database", lambda: None)
    monkeypatch.setattr(chroma_sync.product_store, "get_sync_state", lambda name: None)
    monkeypatch.setattr(
        chroma_sync.product_store,
        "get_products_updated_after",
        lambda updated_after: products,
    )
    monkeypatch.setattr(
        chroma_sync.product_store,
        "set_sync_state",
        lambda name, value: sync_state.update({name: value}),
    )
    monkeypatch.setattr(chroma_sync, "_get_collection", lambda: collection)
    monkeypatch.setattr(
        chroma_sync,
        "get_embedding_function",
        lambda: lambda texts: [[float(index)] for index, _ in enumerate(texts)],
    )

    with caplog.at_level(logging.INFO, logger=chroma_sync.__name__):
        stats = chroma_sync.sync_once()

    assert stats["scanned"] == 2
    assert stats["upserted"] == 1
    assert stats["deleted"] == 1
    assert stats["upserted_product_ids"] == ["p-active"]
    assert stats["deleted_product_ids"] == ["p-inactive"]
    assert collection.upsert_payload["ids"] == ["p-active"]
    assert collection.delete_ids == ["p-inactive"]
    assert sync_state[chroma_sync.SYNC_STATE_NAME] == inactive_updated_at
    assert "ChromaDB 同步完成 scanned=2 upserted=1 deleted=1" in caplog.text
    assert "ChromaDB 同步写入/更新 products=" in caplog.text
    assert "p-active" in caplog.text
    assert "商品 p-active" in caplog.text
    assert "ChromaDB 同步删除 product_ids=" in caplog.text
    assert "p-inactive" in caplog.text


def test_sync_once_logs_completion_without_changes(monkeypatch, caplog):
    last_sync_at = datetime(2026, 1, 1, 10, 0, 0)
    collection = _FakeCollection()

    monkeypatch.setattr(chroma_sync.product_store, "initialize_database", lambda: None)
    monkeypatch.setattr(
        chroma_sync.product_store,
        "get_sync_state",
        lambda name: last_sync_at,
    )
    monkeypatch.setattr(
        chroma_sync.product_store,
        "get_products_updated_after",
        lambda updated_after: [],
    )
    monkeypatch.setattr(chroma_sync, "_get_collection", lambda: collection)

    with caplog.at_level(logging.INFO, logger=chroma_sync.__name__):
        stats = chroma_sync.sync_once()

    assert stats["scanned"] == 0
    assert stats["upserted"] == 0
    assert stats["deleted"] == 0
    assert stats["upserted_product_ids"] == []
    assert stats["deleted_product_ids"] == []
    assert "ChromaDB 同步完成 scanned=0 upserted=0 deleted=0" in caplog.text
    assert "ChromaDB 同步写入/更新 products=" not in caplog.text
    assert "ChromaDB 同步删除 product_ids=" not in caplog.text


def test_periodic_sync_logs_failure_and_keeps_loop_boundary(monkeypatch):
    calls = {"sync": 0}

    def failing_sync_once():
        calls["sync"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(chroma_sync, "sync_once", failing_sync_once)

    asyncio.run(chroma_sync.run_periodic_sync(interval_seconds=0, max_runs=1))

    assert calls == {"sync": 1}


class _FakeCollection:
    def __init__(self) -> None:
        self.upsert_payload = {}
        self.delete_ids = []

    def upsert(self, **kwargs) -> None:
        self.upsert_payload = kwargs

    def delete(self, ids: list[str]) -> None:
        self.delete_ids = ids


def _product(
    product_id: str,
    *,
    updated_at: datetime,
    is_active: bool = True,
    stock: int = 2,
) -> dict:
    return {
        "product_id": product_id,
        "title": f"商品 {product_id}",
        "brand": "品牌",
        "category": "类目",
        "sub_category": "子类目",
        "price": 99.0,
        "stock": stock,
        "is_active": is_active,
        "description": "完整文档",
        "embedding_text": "向量文本",
        "image_url": f"/assets/{product_id}.jpg",
        "updated_at": updated_at,
    }
