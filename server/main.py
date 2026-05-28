"""FastAPI 入口，提供 SSE 流式聊天接口。"""

import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from config import DATASET_DIR, TOP_K
from generator import generate_stream
from retriever import retrieve
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
        products = retrieve(request.message, TOP_K)
        for product in products:
            card = Product(
                product_id=product["product_id"],
                title=product["title"],
                brand=product.get("brand"),
                category=product["category"],
                sub_category=product.get("sub_category"),
                price=product["price"],
                image_url=product.get("image_url"),
            )
            yield {
                "event": "product",
                "data": card.model_dump_json(exclude_none=True),
            }

        async for token in generate_stream(request.message, products):
            yield {
                "event": "token",
                "data": json.dumps({"content": token}, ensure_ascii=False),
            }

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())
