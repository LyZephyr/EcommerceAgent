"""解析结果到块事件的转换与历史文本。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from agent.events import (
    BlockCompareEvent,
    BlockProductEvent,
    BlockTextEvent,
    ParsedFinalResponse,
    ParsedRecommendation,
    StructuredStatusEvent,
)


def recommendation_history_text(
    recommendation: ParsedRecommendation,
    candidates_by_id: dict[str, dict],
) -> str:
    lines = [recommendation.intro]
    for item in recommendation.items:
        product = candidates_by_id.get(item.product_id, {})
        title = product.get("title") or item.product_id
        lines.append(f"[商品] {title}（product_id={item.product_id}）：{item.reason}")
    if recommendation.outro:
        lines.append(f"总结：{recommendation.outro}")
    return "\n".join(line for line in lines if line.strip())


def append_final_response(
    conversation,
    conversation_id: str,
    parsed_response: ParsedFinalResponse,
    candidates_by_id: dict[str, dict],
) -> None:
    clean_text = parsed_response.history_text or parsed_response.clean_text
    if parsed_response.recommendation:
        clean_text = recommendation_history_text(
            parsed_response.recommendation,
            candidates_by_id,
        )
    conversation.append(
        conversation_id,
        {"role": "assistant", "content": clean_text.strip()},
    )


async def events_from_parsed_response(
    parsed_response: ParsedFinalResponse,
    candidates_by_id: dict[str, dict],
    *,
    message_id: str,
) -> AsyncIterator[
    BlockTextEvent
    | BlockProductEvent
    | BlockCompareEvent
    | StructuredStatusEvent
]:
    if parsed_response.recommendation:
        yield StructuredStatusEvent(
            phase="streaming",
            message="正在输出推荐...",
            step=4,
            total_steps=4,
        )
        block_index = 1
        recommendation = parsed_response.recommendation
        if recommendation.intro.strip():
            yield BlockTextEvent(
                message_id=message_id,
                block_id=f"blk-{block_index}",
                content=recommendation.intro,
            )
            block_index += 1
        for item in recommendation.items:
            product = candidates_by_id.get(item.product_id)
            if product:
                yield BlockProductEvent(
                    message_id=message_id,
                    block_id=f"blk-{block_index}",
                    product_id=item.product_id,
                    product_data=product,
                    group=item.group,
                )
                block_index += 1
            if item.reason.strip():
                yield BlockTextEvent(
                    message_id=message_id,
                    block_id=f"blk-{block_index}",
                    content=item.reason,
                )
                block_index += 1
        if recommendation.outro and recommendation.outro.strip():
            yield BlockTextEvent(
                message_id=message_id,
                block_id=f"blk-{block_index}",
                content=recommendation.outro,
            )
        return

    if parsed_response.compare_payload:
        yield BlockCompareEvent(
            message_id=message_id,
            block_id="blk-1",
            payload=parsed_response.compare_payload,
        )
    if parsed_response.clean_text.strip():
        yield BlockTextEvent(
            message_id=message_id,
            block_id="blk-2" if parsed_response.compare_payload else "blk-1",
            content=parsed_response.clean_text,
        )
