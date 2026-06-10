"""FastAPI 入口，提供 SSE 流式聊天接口。"""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

import cart_store
import product_store
from agent import (
    CartEvent,
    CompareEvent,
    ProductEvent,
    StatusEvent,
    TokenEvent,
    run_turn,
)
from config import DATASET_DIR
from conversation import get_or_create_id
from schemas import (
    AddCartItemRequest,
    CartSnapshot,
    ChatRequest,
    Product,
    UpdateCartItemRequest,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    product_store.load_dataset_to_mysql()
    yield


app = FastAPI(title="EcommerceAgent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/assets", StaticFiles(directory=DATASET_DIR), name="assets")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    async def event_stream():
        conv_id = get_or_create_id(request.conversation_id)
        async for event in run_turn(conv_id, request.message):
            if isinstance(event, ProductEvent):
                card = Product(
                    product_id=event.product_data["product_id"],
                    title=event.product_data["title"],
                    brand=event.product_data.get("brand"),
                    category=event.product_data["category"],
                    sub_category=event.product_data.get("sub_category"),
                    price=event.product_data["price"],
                    image_url=event.product_data.get("image_url"),
                )
                cart_store.record_recent_product(
                    conv_id,
                    card.model_dump(exclude_none=True),
                )
                yield {
                    "event": "product",
                    "data": card.model_dump_json(exclude_none=True),
                }
            elif isinstance(event, CompareEvent):
                yield {
                    "event": "compare",
                    "data": json.dumps(event.payload, ensure_ascii=False),
                }
            elif isinstance(event, CartEvent):
                yield {
                    "event": "cart",
                    "data": json.dumps(event.payload, ensure_ascii=False),
                }
            elif isinstance(event, TokenEvent):
                yield {
                    "event": "token",
                    "data": json.dumps(
                        {"content": event.content}, ensure_ascii=False
                    ),
                }
            elif isinstance(event, StatusEvent):
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {"message": event.status}, ensure_ascii=False
                    ),
                }
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())


@app.get("/api/cart", response_model=CartSnapshot)
async def get_cart(conversation_id: str | None = Query(default=None)):
    conv_id = get_or_create_id(conversation_id)
    return cart_store.snapshot(conv_id)


@app.post("/api/cart/items", response_model=CartSnapshot)
async def add_cart_item(request: AddCartItemRequest):
    conv_id = get_or_create_id(request.conversation_id)
    product = cart_store.get_recent_product(conv_id, request.product_id)
    if product is None:
        raise HTTPException(
            status_code=404,
            detail="商品不在当前会话的最近展示商品池中，不能加入购物车。",
        )
    return cart_store.add_item(conv_id, product, request.quantity)


@app.patch("/api/cart/items/{product_id}", response_model=CartSnapshot)
async def update_cart_item(product_id: str, request: UpdateCartItemRequest):
    conv_id = get_or_create_id(request.conversation_id)
    try:
        return cart_store.update_item(conv_id, product_id, request.quantity)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="购物车中不存在该商品。",
        ) from exc


@app.delete("/api/cart/items/{product_id}", response_model=CartSnapshot)
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


@app.delete("/api/cart", response_model=CartSnapshot)
async def clear_cart(conversation_id: str | None = Query(default=None)):
    conv_id = get_or_create_id(conversation_id)
    return cart_store.clear_cart(conv_id)
