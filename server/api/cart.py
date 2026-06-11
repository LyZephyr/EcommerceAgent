"""购物车 HTTP 接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import cart_store
from conversation import get_or_create_id
from schemas import AddCartItemRequest, CartSnapshot, UpdateCartItemRequest

router = APIRouter(tags=["cart"])


@router.get("/api/cart", response_model=CartSnapshot)
async def get_cart(conversation_id: str | None = Query(default=None)):
    conv_id = get_or_create_id(conversation_id)
    return cart_store.snapshot(conv_id)


@router.post("/api/cart/items", response_model=CartSnapshot)
async def add_cart_item(request: AddCartItemRequest):
    conv_id = get_or_create_id(request.conversation_id)
    try:
        return cart_store.add_item(conv_id, request.product_id, request.quantity)
    except cart_store.CartOperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.patch("/api/cart/items/{product_id}", response_model=CartSnapshot)
async def update_cart_item(product_id: str, request: UpdateCartItemRequest):
    conv_id = get_or_create_id(request.conversation_id)
    try:
        return cart_store.update_item(conv_id, product_id, request.quantity)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="购物车中不存在该商品。",
        ) from exc
    except cart_store.CartOperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/api/cart/items/{product_id}", response_model=CartSnapshot)
async def delete_cart_item(
    product_id: str,
    conversation_id: str | None = Query(default=None),
):
    conv_id = get_or_create_id(conversation_id)
    try:
        return cart_store.remove_item(conv_id, product_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="购物车中不存在该商品。",
        ) from exc


@router.delete("/api/cart", response_model=CartSnapshot)
async def clear_cart(conversation_id: str | None = Query(default=None)):
    conv_id = get_or_create_id(conversation_id)
    return cart_store.clear_cart(conv_id)
