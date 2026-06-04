"""FastAPI 入口，提供 SSE 流式聊天接口。"""

import json
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from config import DATASET_DIR, TOP_K
from generator import generate_stream
from intent import parse_intent
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


_MAX_TAG_BUFFER = 500


@app.post("/api/chat")
async def chat(request: ChatRequest):
    async def event_stream():
        intent = await parse_intent(request.message)
        candidates = retrieve(request.message, TOP_K, intent)
        candidates_by_id = {p["product_id"]: p for p in candidates}

        buffer: list[str] = []
        tag_parsed = False

        async for token in generate_stream(request.message, candidates):
            if not tag_parsed:
                buffer.append(token)
                joined = "".join(buffer)
                if "</R>" in joined:
                    tag_parsed = True
                    recommended_ids, remainder = _extract_recommend_tag(joined)
                    for evt in _product_events(recommended_ids, candidates, candidates_by_id):
                        yield evt
                    if remainder.strip():
                        yield _token_event(remainder)
                elif len(joined) > _MAX_TAG_BUFFER:
                    tag_parsed = True
                    yield _token_event(joined)
                continue

            yield _token_event(token)

        if not tag_parsed:
            joined = "".join(buffer)
            recommended_ids, text = _extract_recommend_tag(joined)
            for evt in _product_events(recommended_ids, candidates, candidates_by_id):
                yield evt
            if text.strip():
                yield _token_event(text)

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())


def _extract_recommend_tag(text: str) -> tuple[list[str], str]:
    """从文本中提取 <R>...</R> 标记里的商品 ID 列表，返回 (ids, 剩余文本)。"""
    match = re.search(r"<R>(.*?)</R>\n?", text)
    if not match:
        return [], text
    ids_str = match.group(1).strip()
    ids = [pid.strip() for pid in ids_str.split(",") if pid.strip()] if ids_str else []
    remaining = text[: match.start()] + text[match.end() :]
    return ids, remaining


def _product_events(
    recommended_ids: list[str],
    candidates: list[dict],
    candidates_by_id: dict[str, dict],
):
    """生成 product SSE 事件。只发送 LLM 明确推荐的商品；无推荐时不展示卡片。"""
    if recommended_ids:
        products_to_send = [candidates_by_id[pid] for pid in recommended_ids if pid in candidates_by_id]
    else:
        products_to_send = []

    for p in products_to_send:
        card = Product(
            product_id=p["product_id"],
            title=p["title"],
            brand=p.get("brand"),
            category=p["category"],
            sub_category=p.get("sub_category"),
            price=p["price"],
            image_url=p.get("image_url"),
        )
        yield {"event": "product", "data": card.model_dump_json(exclude_none=True)}


def _token_event(content: str) -> dict:
    return {"event": "token", "data": json.dumps({"content": content}, ensure_ascii=False)}
