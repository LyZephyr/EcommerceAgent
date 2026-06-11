"""商品详情 HTTP 接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import product_store
from schemas import ProductDetail

router = APIRouter(tags=["products"])


@router.get("/api/products/{product_id}", response_model=ProductDetail)
async def get_product_detail(product_id: str):
    product_detail = product_store.get_product_detail(product_id)
    if product_detail is None:
        raise HTTPException(status_code=404, detail="商品不存在。")
    return product_detail
