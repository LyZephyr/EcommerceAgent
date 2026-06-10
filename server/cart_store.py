"""内存购物车与最近展示商品池。"""

from __future__ import annotations

from collections import deque
from copy import deepcopy

_RECENT_PRODUCT_LIMIT = 20

_carts: dict[str, dict[str, dict]] = {}
_recent_products: dict[str, deque[dict]] = {}


def record_recent_product(conversation_id: str, product: dict) -> None:
    product_snapshot = _product_snapshot(product)
    products = _recent_products.setdefault(
        conversation_id,
        deque(maxlen=_RECENT_PRODUCT_LIMIT),
    )
    product_id = product_snapshot["product_id"]
    remaining = [item for item in products if item["product_id"] != product_id]
    products.clear()
    products.extend(remaining)
    products.append(product_snapshot)


def get_recent_product(conversation_id: str, product_id: str) -> dict | None:
    for product in _recent_products.get(conversation_id, ()):
        if product["product_id"] == product_id:
            return deepcopy(product)
    return None


def get_recent_product_by_position(conversation_id: str, position: int) -> dict | None:
    if position < 1:
        return None
    products = list(_recent_products.get(conversation_id, ()))
    index = position - 1
    if index >= len(products):
        return None
    return deepcopy(products[index])


def list_recent_products(conversation_id: str) -> list[dict]:
    return [deepcopy(product) for product in _recent_products.get(conversation_id, ())]


def add_item(conversation_id: str, product: dict, quantity: int = 1) -> dict:
    product_snapshot = _product_snapshot(product)
    cart = _carts.setdefault(conversation_id, {})
    product_id = product_snapshot["product_id"]
    if product_id in cart:
        cart[product_id]["quantity"] += quantity
    else:
        cart[product_id] = {**product_snapshot, "quantity": quantity}
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
    cart[product_id]["quantity"] = quantity
    return snapshot(conversation_id)


def clear_cart(conversation_id: str) -> dict:
    _carts[conversation_id] = {}
    return snapshot(conversation_id)


def snapshot(conversation_id: str) -> dict:
    items = [
        deepcopy(item)
        for item in _carts.get(conversation_id, {}).values()
    ]
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
    }


def _product_snapshot(product: dict) -> dict:
    return {
        "product_id": str(product["product_id"]),
        "title": str(product["title"]),
        "brand": product.get("brand"),
        "category": str(product["category"]),
        "sub_category": product.get("sub_category"),
        "price": float(product["price"]),
        "image_url": product.get("image_url"),
    }
