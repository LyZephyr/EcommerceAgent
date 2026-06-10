"""内存购物车与近期展示商品池。"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import UTC, datetime
from math import isclose

import product_store

_RECENT_PRODUCT_LIMIT = 20

_carts: dict[str, dict[str, dict]] = {}
_recent_product_entries: dict[str, deque[dict]] = {}


class CartOperationError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def record_recent_product(conversation_id: str, product: dict) -> None:
    entry = _recent_product_entry(product)
    entries = _recent_product_entries.setdefault(
        conversation_id,
        deque(maxlen=_RECENT_PRODUCT_LIMIT),
    )
    product_id = entry["product_id"]
    remaining = [item for item in entries if item["product_id"] != product_id]
    entries.clear()
    entries.extend(remaining)
    entries.append(entry)


def get_recent_product_entry(conversation_id: str, product_id: str) -> dict | None:
    for entry in _recent_product_entries.get(conversation_id, ()):
        if entry["product_id"] == product_id:
            return deepcopy(entry)
    return None


def list_recent_product_entries(conversation_id: str) -> list[dict]:
    return [
        deepcopy(entry)
        for entry in reversed(_recent_product_entries.get(conversation_id, ()))
    ]


def list_recent_products(conversation_id: str) -> list[dict]:
    entries = list_recent_product_entries(conversation_id)
    product_ids = [entry["product_id"] for entry in entries]
    products = product_store.get_products_by_ids(product_ids)
    products_by_id = {product["product_id"]: product for product in products}
    recent_products = []

    for entry in entries:
        product = products_by_id.get(entry["product_id"])
        if product is None:
            continue
        recent_products.append(
            _product_snapshot(product)
            | {
                "is_active": bool(product.get("is_active")),
                "displayed_price": entry["displayed_price"],
                "displayed_at": entry["displayed_at"],
            }
        )
    return recent_products


def add_item(conversation_id: str, product_id: str, quantity: int = 1) -> dict:
    if quantity < 1:
        raise CartOperationError("加购数量必须至少为 1。", status_code=422)

    recent_entry = get_recent_product_entry(conversation_id, str(product_id))
    if recent_entry is None:
        raise CartOperationError(
            "商品不在当前会话的近期展示商品池中，不能加入购物车。",
            status_code=404,
        )

    product_snapshot = _active_product_snapshot(product_id)
    cart = _carts.setdefault(conversation_id, {})
    product_id = product_snapshot["product_id"]
    current_quantity = cart.get(product_id, {}).get("quantity", 0)
    requested_quantity = current_quantity + quantity
    _ensure_stock(product_snapshot, requested_quantity)

    if product_id in cart:
        cart[product_id]["quantity"] += quantity
    else:
        cart[product_id] = {
            "product_id": product_id,
            "quantity": quantity,
            "last_seen_price": recent_entry["displayed_price"],
        }

    return snapshot(conversation_id)


def remove_item(conversation_id: str, product_id: str) -> dict:
    cart = _carts.setdefault(conversation_id, {})
    if product_id not in cart:
        raise KeyError(product_id)
    del cart[product_id]
    return snapshot(conversation_id)


def update_item(conversation_id: str, product_id: str, quantity: int) -> dict:
    cart = _carts.setdefault(conversation_id, {})
    if product_id not in cart:
        raise KeyError(product_id)
    if quantity < 1:
        raise CartOperationError("商品数量必须至少为 1。", status_code=422)

    product_snapshot = _active_product_snapshot(product_id)
    _ensure_stock(product_snapshot, quantity)
    cart[product_id]["quantity"] = quantity
    return snapshot(conversation_id)


def clear_cart(conversation_id: str) -> dict:
    _carts[conversation_id] = {}
    return snapshot(conversation_id)


def snapshot(conversation_id: str) -> dict:
    cart = _carts.get(conversation_id, {})
    messages: list[str] = []
    items = _hydrate_cart_items(cart, messages)
    total_quantity = sum(item["quantity"] for item in items)
    total_price = round(
        sum(item["price"] * item["quantity"] for item in items),
        2,
    )
    return {
        "conversation_id": conversation_id,
        "items": items,
        "total_quantity": total_quantity,
        "total_price": total_price,
        "messages": messages,
    }


def _product_snapshot(product: dict) -> dict:
    return product_store.product_card_payload(product)


def _recent_product_entry(product: dict) -> dict:
    return {
        "product_id": str(product["product_id"]),
        "displayed_price": float(product["price"]),
        "displayed_at": datetime.now(UTC).isoformat(),
    }


def _active_product_snapshot(product_id: str) -> dict:
    product = product_store.get_product_by_id(str(product_id))
    if product is None:
        raise CartOperationError("商品不存在，无法加入购物车。", status_code=404)
    if not product.get("is_active"):
        raise CartOperationError("商品已下架，无法加入购物车。", status_code=409)
    if int(product.get("stock") or 0) <= 0:
        raise CartOperationError("商品库存不足，无法加入购物车。", status_code=409)
    return _product_snapshot(product) | {"is_active": True}


def _ensure_stock(product: dict, quantity: int) -> None:
    stock = int(product.get("stock") or 0)
    if quantity > stock:
        raise CartOperationError(
            f"商品库存不足，当前库存 {stock} 件。",
            status_code=409,
        )


def _hydrate_cart_items(cart: dict[str, dict], messages: list[str]) -> list[dict]:
    product_ids = list(cart.keys())
    products = product_store.get_products_by_ids(product_ids)
    products_by_id = {product["product_id"]: product for product in products}
    items: list[dict] = []

    for product_id in product_ids:
        product = products_by_id.get(product_id)
        if product is None:
            del cart[product_id]
            messages.append(f"商品 {product_id} 已不存在，已从购物车移除。")
            continue
        if not product.get("is_active"):
            del cart[product_id]
            messages.append(f"「{product['title']}」已下架，已从购物车移除。")
            continue

        quantity = int(cart[product_id]["quantity"])
        _append_price_change_message(cart[product_id], product, messages)
        item = _product_snapshot(product) | {
            "quantity": quantity,
            "is_active": True,
            "unavailable_reason": _unavailable_reason(product, quantity),
        }
        items.append(item)
    return items


def _unavailable_reason(product: dict, quantity: int) -> str | None:
    stock = int(product.get("stock") or 0)
    if stock <= 0:
        return "库存不足"
    if quantity > stock:
        return f"库存不足，当前库存 {stock} 件"
    return None


def _append_price_change_message(
    cart_item: dict,
    product: dict,
    messages: list[str],
) -> None:
    latest_price = float(product["price"])
    last_seen_price = cart_item.get("last_seen_price")
    if last_seen_price is not None and not isclose(
        float(last_seen_price),
        latest_price,
        rel_tol=0,
        abs_tol=0.001,
    ):
        messages.append(
            f"「{product['title']}」价格已更新：已从 ¥{float(last_seen_price):.2f} "
            f"更新为 ¥{latest_price:.2f}。"
        )
    cart_item["last_seen_price"] = latest_price
