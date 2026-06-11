"""HTTP API 路由注册。"""

from __future__ import annotations

from fastapi import FastAPI

from api.cart import router as cart_router
from api.chat import router as chat_router
from api.products import router as products_router


def include_api_routes(app: FastAPI) -> None:
    app.include_router(chat_router)
    app.include_router(products_router)
    app.include_router(cart_router)
