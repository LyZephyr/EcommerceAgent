"""Agent 事件与解析结果数据类。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.contracts import RecentProductEntry


@dataclass
class StructuredStatusEvent:
    phase: str
    message: str
    step: int | None = None
    total_steps: int | None = None


@dataclass
class CartEvent:
    payload: dict


@dataclass
class BlockTextEvent:
    message_id: str
    block_id: str
    content: str
    attempt_id: str = "attempt-1"


@dataclass
class BlockTextDeltaEvent:
    message_id: str
    block_id: str
    content: str
    attempt_id: str = "attempt-1"


@dataclass
class BlockProductEvent:
    message_id: str
    block_id: str
    product_id: str
    product_data: dict
    group: str | None = None
    attempt_id: str = "attempt-1"


@dataclass
class BlockCompareEvent:
    message_id: str
    block_id: str
    payload: dict
    attempt_id: str = "attempt-1"


@dataclass
class MessageStartEvent:
    message_id: str
    attempt_id: str
    provisional: bool = True


@dataclass
class MessageResetEvent:
    message_id: str
    attempt_id: str
    reason: str


@dataclass
class MessageCommitEvent:
    message_id: str
    attempt_id: str
    recent_products: list[RecentProductEntry]


@dataclass
class RecommendationItem:
    product_id: str
    reason: str
    group: str | None = None


@dataclass
class ParsedRecommendation:
    intro: str
    items: list[RecommendationItem]
    outro: str | None = None


@dataclass
class ParsedFinalResponse:
    recommendation: ParsedRecommendation | None
    compare_payload: dict | None
    clean_text: str
    history_text: str | None = None

    @property
    def recommended_ids(self) -> list[str]:
        if not self.recommendation:
            return []
        return [item.product_id for item in self.recommendation.items]
