"""FastAPI 入口，提供 SSE 流式聊天接口。"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

import cart_store
import chroma_sync
import product_store
from agent import (
    AgentRecoveryExhausted,
    BlockCompareEvent,
    BlockProductEvent,
    BlockTextDeltaEvent,
    BlockTextEvent,
    CartEvent,
    StructuredStatusEvent,
    run_turn,
)
from config import DATASET_DIR
from conversation import get_or_create_id
from logging_config import configure_logging
from schemas import (
    AddCartItemRequest,
    CartSnapshot,
    ChatRequest,
    Product,
    ProductDetail,
    UpdateCartItemRequest,
)

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    product_store.load_dataset_to_mysql()
    sync_task = asyncio.create_task(chroma_sync.run_periodic_sync())
    try:
        yield
    finally:
        sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await sync_task


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
async def chat(chat_request: ChatRequest, http_request: Request):
    async def event_stream():
        conv_id = get_or_create_id(chat_request.conversation_id)
        turn_events = run_turn(conv_id, chat_request.message)
        disconnected = False
        try:
            async for event in turn_events:
                if await http_request.is_disconnected():
                    disconnected = True
                    logger.info("chat_stream_disconnected conversation_id=%s", conv_id)
                    logger.info("llm_call_cancelled conversation_id=%s", conv_id)
                    await turn_events.aclose()
                    return
                if isinstance(event, CartEvent):
                    yield {
                        "event": "cart",
                        "data": json.dumps(event.payload, ensure_ascii=False),
                    }
                elif isinstance(event, BlockTextEvent):
                    yield {
                        "event": "block",
                        "data": json.dumps(
                            {
                                "type": "text",
                                "message_id": event.message_id,
                                "block_id": event.block_id,
                                "content": event.content,
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif isinstance(event, BlockTextDeltaEvent):
                    yield {
                        "event": "block",
                        "data": json.dumps(
                            {
                                "type": "text_delta",
                                "message_id": event.message_id,
                                "block_id": event.block_id,
                                "content": event.content,
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif isinstance(event, BlockProductEvent):
                    card = _product_card_from_data(event.product_data)
                    if event.group:
                        card.group_label = event.group
                    cart_store.record_recent_product(
                        conv_id,
                        card.model_dump(exclude_none=True),
                    )
                    payload = {
                        "type": "product",
                        "message_id": event.message_id,
                        "block_id": event.block_id,
                        "product": card.model_dump(exclude_none=True),
                    }
                    if event.group:
                        payload["group"] = event.group
                    yield {
                        "event": "block",
                        "data": json.dumps(payload, ensure_ascii=False),
                    }
                elif isinstance(event, BlockCompareEvent):
                    yield {
                        "event": "block",
                        "data": json.dumps(
                            {
                                "type": "compare",
                                "message_id": event.message_id,
                                "block_id": event.block_id,
                                "compare": event.payload,
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif isinstance(event, StructuredStatusEvent):
                    data = {
                        "phase": event.phase,
                        "message": event.message,
                        "step": event.step,
                        "total_steps": event.total_steps,
                    }
                    yield {
                        "event": "status",
                        "data": json.dumps(data, ensure_ascii=False),
                    }
        except asyncio.CancelledError:
            disconnected = True
            logger.info("chat_stream_cancelled conversation_id=%s", conv_id)
            logger.info("llm_call_cancelled conversation_id=%s", conv_id)
            await turn_events.aclose()
            raise
        except AgentRecoveryExhausted as exc:
            logger.exception(
                "chat_agent_recovery_exhausted conversation_id=%s payload=%s",
                conv_id,
                json.dumps(exc.to_payload(), ensure_ascii=False),
            )
            yield {
                "event": "error",
                "data": json.dumps(
                    {"message": "模型输出连续异常，已停止本轮回复，请稍后重试。"},
                    ensure_ascii=False,
                ),
            }
        except Exception:
            logger.exception("chat_stream_failed conversation_id=%s", conv_id)
            yield {
                "event": "error",
                "data": json.dumps(
                    {"message": "服务处理失败，请稍后重试。"},
                    ensure_ascii=False,
                ),
            }
        finally:
            if not disconnected:
                yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())


def _product_card_from_data(product_data: dict) -> Product:
    return Product(**product_store.product_card_payload(product_data))


@app.get("/api/products/{product_id}", response_model=ProductDetail)
async def get_product_detail(product_id: str):
    product_detail = product_store.get_product_detail(product_id)
    if product_detail is None:
        raise HTTPException(status_code=404, detail="商品不存在。")
    return product_detail


@app.get("/api/cart", response_model=CartSnapshot)
async def get_cart(conversation_id: str | None = Query(default=None)):
    conv_id = get_or_create_id(conversation_id)
    return cart_store.snapshot(conv_id)


@app.post("/api/cart/items", response_model=CartSnapshot)
async def add_cart_item(request: AddCartItemRequest):
    conv_id = get_or_create_id(request.conversation_id)
    try:
        return cart_store.add_item(conv_id, request.product_id, request.quantity)
    except cart_store.CartOperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
    except cart_store.CartOperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
