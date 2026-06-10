"""MySQL 商品权威源。

负责初始化商品表、把数据集幂等写入 MySQL，并提供后续检索链路需要的
商品快照读取接口。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote_plus

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    case,
    create_engine,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.mysql import LONGTEXT, insert
from sqlalchemy.engine import Engine

from config import (
    DATASET_DIR,
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)
from ingest import build_embedding_text, build_full_document, load_products

_metadata = MetaData()
_engine: Engine | None = None

products_table = Table(
    "products",
    _metadata,
    Column("product_id", String(64), primary_key=True),
    Column("title", String(512), nullable=False),
    Column("brand", String(128), nullable=False, default=""),
    Column("category", String(128), nullable=False, default=""),
    Column("sub_category", String(128), nullable=False, default=""),
    Column("price", Numeric(12, 2), nullable=False),
    Column("stock", Integer, nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("description", LONGTEXT, nullable=False),
    Column("image_url", String(512), nullable=False),
    Column("raw_payload", LONGTEXT, nullable=False),
    Column("embedding_text", LONGTEXT, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_unicode_ci",
)

sync_state_table = Table(
    "sync_state",
    _metadata,
    Column("name", String(128), primary_key=True),
    Column("last_sync_at", DateTime, nullable=False),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_unicode_ci",
)


def initialize_database() -> None:
    """创建数据库和 products 表。"""
    server_engine = create_engine(_mysql_url(include_database=False), future=True)
    database_name = MYSQL_DATABASE.replace("`", "``")
    with server_engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    server_engine.dispose()

    _metadata.create_all(get_engine())


def load_dataset_to_mysql(dataset_dir: str | None = None) -> int:
    """扫描商品数据集并幂等 upsert 到 MySQL，返回写入商品数量。"""
    initialize_database()
    products = load_products(dataset_dir or DATASET_DIR)
    if not products:
        raise RuntimeError(f"未在数据集目录中找到商品 JSON：{dataset_dir or DATASET_DIR}")

    records = [product_to_record(product) for product in products]
    upsert_products(records)
    return len(records)


def upsert_products(records: list[dict]) -> None:
    if not records:
        return

    statement = insert(products_table).values(records)
    changed_columns = [
        "title",
        "brand",
        "category",
        "sub_category",
        "price",
        "stock",
        "is_active",
        "description",
        "image_url",
        "raw_payload",
        "embedding_text",
    ]
    changed_condition = or_(
        *(
            products_table.c[column_name] != statement.inserted[column_name]
            for column_name in changed_columns
        )
    )
    update_columns = {
        column.name: statement.inserted[column.name]
        for column in products_table.columns
        if column.name not in {"product_id", "created_at", "updated_at"}
    }
    update_columns["updated_at"] = case(
        (changed_condition, func.now()),
        else_=products_table.c.updated_at,
    )
    statement = statement.on_duplicate_key_update(**update_columns)

    with get_engine().begin() as connection:
        connection.execute(statement)


def get_products_by_ids(product_ids: list[str]) -> list[dict]:
    """按传入顺序返回商品快照，缺失的 product_id 会被忽略。"""
    if not product_ids:
        return []

    unique_ids = list(dict.fromkeys(product_ids))
    statement = select(products_table).where(products_table.c.product_id.in_(unique_ids))
    with get_engine().connect() as connection:
        rows = connection.execute(statement).mappings().all()

    products_by_id = {
        str(row["product_id"]): _row_to_product(row)
        for row in rows
    }
    return [
        products_by_id[product_id]
        for product_id in unique_ids
        if product_id in products_by_id
    ]


def get_product_by_id(product_id: str) -> dict | None:
    products = get_products_by_ids([product_id])
    return products[0] if products else None


def get_product_detail(product_id: str) -> dict | None:
    """返回商品详情页数据，不暴露原始 raw_payload。"""
    product = get_product_by_id(product_id)
    if product is None:
        return None

    raw_payload = _loads_raw_payload(product)
    knowledge = raw_payload.get("rag_knowledge") or {}
    reviews = knowledge.get("user_reviews") or []

    return product_card_payload(product) | {
        "description": product.get("description") or "",
        "specs": _specs_from_raw_payload(raw_payload),
        "faq": _faq_from_raw_payload(raw_payload),
        "review_summary": _review_summary_from_raw_payload(reviews),
    }


def product_card_payload(product: dict, *, group_label: str | None = None) -> dict:
    """构造聊天商品卡片和详情页共用的公开商品字段。"""
    stock_status, unavailable_reason = product_availability(product)
    payload = {
        "product_id": str(product["product_id"]),
        "title": str(product["title"]),
        "brand": product.get("brand"),
        "category": str(product["category"]),
        "sub_category": product.get("sub_category"),
        "price": float(product["price"]),
        "image_url": product.get("image_url"),
        "stock": int(product.get("stock") or 0),
        "detail_url": f"/api/products/{product['product_id']}",
        "landing_url": _landing_url(product),
        "highlights": _highlights_from_product(product),
        "stock_status": stock_status,
        "unavailable_reason": unavailable_reason,
        "group_label": group_label,
    }
    return payload


def product_availability(product: dict) -> tuple[str, str | None]:
    stock = int(product.get("stock") or 0)
    if not product.get("is_active"):
        return "inactive", "商品已下架"
    if stock <= 0:
        return "out_of_stock", "商品库存不足"
    if stock <= 3:
        return "low_stock", None
    return "in_stock", None


def get_products_updated_after(updated_after: datetime) -> list[dict]:
    statement = (
        select(products_table)
        .where(products_table.c.updated_at > updated_after)
        .order_by(products_table.c.updated_at.asc(), products_table.c.product_id.asc())
    )
    with get_engine().connect() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_row_to_product(row) for row in rows]


def list_active_products() -> list[dict]:
    statement = (
        select(products_table)
        .where(products_table.c.is_active.is_(True))
        .order_by(products_table.c.product_id.asc())
    )
    with get_engine().connect() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_row_to_product(row) for row in rows]


def count_products() -> int:
    statement = select(func.count()).select_from(products_table)
    with get_engine().connect() as connection:
        return int(connection.execute(statement).scalar_one())


def get_sync_state(name: str) -> datetime | None:
    statement = select(sync_state_table.c.last_sync_at).where(
        sync_state_table.c.name == name
    )
    with get_engine().connect() as connection:
        return connection.execute(statement).scalar_one_or_none()


def set_sync_state(name: str, last_sync_at: datetime) -> None:
    statement = insert(sync_state_table).values(
        name=name,
        last_sync_at=last_sync_at,
    )
    statement = statement.on_duplicate_key_update(
        last_sync_at=statement.inserted.last_sync_at,
        updated_at=func.now(),
    )
    with get_engine().begin() as connection:
        connection.execute(statement)


def product_to_record(product: dict) -> dict:
    prices = [sku["price"] for sku in product.get("skus", []) if "price" in sku]
    price = float(product.get("base_price") or min(prices))
    return {
        "product_id": str(product["product_id"]),
        "title": str(product["title"]),
        "brand": str(product.get("brand") or ""),
        "category": str(product.get("category") or ""),
        "sub_category": str(product.get("sub_category") or ""),
        "price": price,
        "stock": int(product.get("stock", 2)),
        "is_active": bool(product.get("is_active", True)),
        "description": build_full_document(product),
        "image_url": _image_url(product),
        "raw_payload": json.dumps(product, ensure_ascii=False),
        "embedding_text": build_embedding_text(product),
    }


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            _mysql_url(include_database=True),
            future=True,
            pool_pre_ping=True,
        )
    return _engine


def _mysql_url(*, include_database: bool) -> str:
    user = quote_plus(MYSQL_USER)
    password = quote_plus(MYSQL_PASSWORD)
    database = f"/{quote_plus(MYSQL_DATABASE)}" if include_database else "/"
    return (
        f"mysql+pymysql://{user}:{password}@{MYSQL_HOST}:{MYSQL_PORT}"
        f"{database}?charset=utf8mb4"
    )


def _row_to_product(row) -> dict:
    product = dict(row)
    product["price"] = _to_float(product["price"])
    product["stock"] = int(product["stock"])
    product["is_active"] = bool(product["is_active"])
    return product


def _to_float(value) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _image_url(product: dict) -> str:
    category_dir = product.get("_category_dir", "")
    product_id = product["product_id"]
    return f"/assets/{category_dir}/images/{product_id}_live.jpg"


def _loads_raw_payload(product: dict) -> dict:
    raw_payload = product.get("raw_payload")
    if not raw_payload:
        return {}
    return json.loads(raw_payload)


def _landing_url(product: dict) -> str | None:
    raw_payload = _loads_raw_payload(product)
    landing_url = raw_payload.get("landing_url") or raw_payload.get("url")
    return str(landing_url) if landing_url else None


def _highlights_from_product(product: dict) -> list[str]:
    raw_payload = _loads_raw_payload(product)
    knowledge = raw_payload.get("rag_knowledge") or {}
    highlights = raw_payload.get("highlights")
    if isinstance(highlights, list):
        return [str(item).strip() for item in highlights[:4] if str(item).strip()]

    marketing = str(knowledge.get("marketing_description") or "")
    sentences = _split_sentences(marketing)
    return sentences[:4]


def _specs_from_raw_payload(raw_payload: dict) -> list[dict[str, str]]:
    specs_by_name: dict[str, list[str]] = {}
    for sku in raw_payload.get("skus") or []:
        properties = sku.get("properties") or {}
        for name, value in properties.items():
            if value is None:
                continue
            text_value = str(value).strip()
            if not text_value:
                continue
            values = specs_by_name.setdefault(str(name), [])
            if text_value not in values:
                values.append(text_value)
    return [
        {"name": name, "value": " / ".join(values)}
        for name, values in specs_by_name.items()
        if values
    ]


def _faq_from_raw_payload(raw_payload: dict) -> list[dict[str, str]]:
    knowledge = raw_payload.get("rag_knowledge") or {}
    faq_items = knowledge.get("official_faq") or []
    return [
        {
            "question": str(item.get("question") or "").strip(),
            "answer": str(item.get("answer") or "").strip(),
        }
        for item in faq_items[:5]
        if str(item.get("question") or "").strip()
        and str(item.get("answer") or "").strip()
    ]


def _review_summary_from_raw_payload(reviews: list[dict]) -> dict:
    ratings = [
        float(review["rating"])
        for review in reviews
        if isinstance(review, dict) and review.get("rating") is not None
    ]
    average_rating = round(sum(ratings) / len(ratings), 1) if ratings else None
    highlights = [
        str(review.get("content") or "").strip()
        for review in reviews[:3]
        if isinstance(review, dict) and str(review.get("content") or "").strip()
    ]
    return {
        "average_rating": average_rating,
        "total_count": len(reviews),
        "highlights": highlights,
    }


def _split_sentences(text: str) -> list[str]:
    parts = [
        part.strip()
        for part in re.split(r"[。！？!?；;\n]+", text)
        if part.strip()
    ]
    return [part[:48] for part in parts if part]


if __name__ == "__main__":
    loaded_count = load_dataset_to_mysql()
    total_count = count_products()
    print(f"已加载 {loaded_count} 个商品到 MySQL，products 当前共 {total_count} 条。")
