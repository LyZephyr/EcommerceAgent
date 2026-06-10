"""Pydantic 数据模型，定义 API 请求/响应结构。"""

from typing import Literal

from pydantic import BaseModel, Field

StockStatus = Literal["in_stock", "low_stock", "out_of_stock", "inactive"]


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
    stock: int | None = None
    detail_url: str | None = None
    landing_url: str | None = None
    highlights: list[str] = Field(default_factory=list)
    stock_status: StockStatus
    unavailable_reason: str | None = None
    group_label: str | None = None


class ProductFaq(BaseModel):
    question: str
    answer: str


class ProductReviewSummary(BaseModel):
    average_rating: float | None = None
    total_count: int
    highlights: list[str] = Field(default_factory=list)


class ProductDetail(Product):
    description: str
    specs: list[dict[str, str]] = Field(default_factory=list)
    faq: list[ProductFaq] = Field(default_factory=list)
    review_summary: ProductReviewSummary


class CartItem(Product):
    quantity: int = Field(ge=1)
    is_active: bool | None = None
    unavailable_reason: str | None = None


class CartSnapshot(BaseModel):
    conversation_id: str
    items: list[CartItem]
    total_quantity: int
    total_price: float
    messages: list[str] = Field(default_factory=list)


class AddCartItemRequest(BaseModel):
    conversation_id: str | None = None
    product_id: str
    quantity: int = Field(default=1, ge=1)


class UpdateCartItemRequest(BaseModel):
    conversation_id: str | None = None
    quantity: int = Field(ge=1)
