"""Pydantic 数据模型，定义 API 请求/响应结构。"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class Product(BaseModel):
    product_id: str
    title: str
    category: str
    price: float
    brand: str | None = None
    sub_category: str | None = None
    image_url: str | None = None


class CartItem(Product):
    quantity: int = Field(ge=1)


class CartSnapshot(BaseModel):
    conversation_id: str
    items: list[CartItem]
    total_quantity: int
    total_price: float


class AddCartItemRequest(BaseModel):
    conversation_id: str | None = None
    product_id: str
    quantity: int = Field(default=1, ge=1)


class UpdateCartItemRequest(BaseModel):
    conversation_id: str | None = None
    quantity: int = Field(ge=1)
