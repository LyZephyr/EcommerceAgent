"""FastAPI 入口，提供 SSE 流式聊天接口。"""

import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from agent import CompareEvent, ProductEvent, StatusEvent, TokenEvent, run_turn
from config import DATASET_DIR
from conversation import get_or_create_id
from schemas import ChatRequest, Product

app = FastAPI(title="EcommerceAgent API")

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
                yield {
                    "event": "product",
                    "data": card.model_dump_json(exclude_none=True),
                }
            elif isinstance(event, CompareEvent):
                yield {
                    "event": "compare",
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
