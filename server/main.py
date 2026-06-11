"""FastAPI 应用入口。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import chroma_sync
import product_store
from api import include_api_routes
from config import DATASET_DIR
from logging_config import configure_logging

configure_logging()


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


def create_app() -> FastAPI:
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

    include_api_routes(app)
    return app


app = create_app()
