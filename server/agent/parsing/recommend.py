"""<R> 推荐标记解析与统一校验。"""

from __future__ import annotations

import re

from agent.candidates import recommend_group_context
from agent.constants import ITEM_ATTR_VALUE_RE, ITEM_OPEN_TAG_RE, RECOMMEND_FIELD_LIMITS
from agent.errors import RecoverableAgentError
from agent.events import ParsedRecommendation, RecommendationItem
from agent.parsing.mobile import validate_mobile_visible_reply


def validate_item_attr_value(value: str, *, raw_output: str, attr_name: str) -> None:
    if not value or not ITEM_ATTR_VALUE_RE.fullmatch(value):
        raise RecoverableAgentError(
            "recommend_marker_invalid_attr",
            "<ITEM> 属性值只能包含字母、数字、汉字、-、_、空格、冒号和斜杠。",
            raw_output=raw_output,
            details={"attr_name": attr_name, "value": value},
        )


def validate_item_attributes(
    product_id: str,
    group: str | None,
    *,
    raw_output: str,
) -> None:
    validate_item_attr_value(product_id, raw_output=raw_output, attr_name="id")
    if group is not None:
        validate_item_attr_value(group, raw_output=raw_output, attr_name="group")


def validate_item_membership(
    product_id: str,
    group: str | None,
    *,
    raw_output: str,
    candidate_ids: set[str],
    group_product_ids: dict[str, set[str]],
    require_group: bool,
) -> None:
    if product_id not in candidate_ids:
        raise RecoverableAgentError(
            "recommend_marker_unknown_ids",
            "<ITEM> 中包含本轮工具结果里不存在的商品 ID。",
            raw_output=raw_output,
            details={
                "unknown_ids": [product_id],
                "candidate_ids": sorted(candidate_ids),
            },
        )
    if require_group:
        if not group:
            raise RecoverableAgentError(
                "recommend_marker_invalid_group",
                "多 request 推荐场景中每个 <ITEM> 都必须包含 group。",
                raw_output=raw_output,
                details={"valid_groups": sorted(group_product_ids)},
            )
        if group not in group_product_ids:
            raise RecoverableAgentError(
                "recommend_marker_invalid_group",
                "<ITEM> group 必须来自本轮 retrieve_products 的 request label。",
                raw_output=raw_output,
                details={"group": group, "valid_groups": sorted(group_product_ids)},
            )
        if product_id not in group_product_ids[group]:
            raise RecoverableAgentError(
                "recommend_marker_invalid_group",
                "<ITEM> id 必须属于对应 group 的候选商品。",
                raw_output=raw_output,
                details={"group": group, "product_id": product_id},
            )
    elif group:
        raise RecoverableAgentError(
            "recommend_marker_invalid_group",
            "单 request 或无 label 推荐场景中 <ITEM> 不允许包含 group。",
            raw_output=raw_output,
            details={"group": group},
        )


def parse_item_open_tag(tag: str, *, raw_output: str) -> tuple[str, str | None]:
    match = ITEM_OPEN_TAG_RE.fullmatch(tag)
    if not match:
        raise RecoverableAgentError(
            "recommend_marker_invalid_attr",
            "<ITEM> 开始标签只允许 id 和可选 group 属性。",
            raw_output=raw_output,
            details={"tag": tag},
        )
    product_id = match.group(1).strip()
    group = (match.group(2) or "").strip() or None
    validate_item_attributes(product_id, group, raw_output=raw_output)
    return product_id, group


def validate_streaming_item(
    product_id: str,
    group: str | None,
    *,
    raw_output: str,
    candidate_ids: set[str],
    candidate_groups: list[dict],
) -> None:
    group_product_ids, require_group = recommend_group_context(candidate_groups)
    validate_item_membership(
        product_id,
        group,
        raw_output=raw_output,
        candidate_ids=candidate_ids,
        group_product_ids=group_product_ids,
        require_group=require_group,
    )


def parse_recommendation_item_tag(
    tag: str,
    *,
    raw_output: str,
    candidate_ids: set[str],
    candidate_groups: list[dict],
) -> RecommendationItem:
    product_id, group = parse_item_open_tag(tag, raw_output=raw_output)
    validate_streaming_item(
        product_id,
        group,
        raw_output=raw_output,
        candidate_ids=candidate_ids,
        candidate_groups=candidate_groups,
    )
    return RecommendationItem(product_id=product_id, reason="", group=group)


RECOMMEND_START_TAG_RE = re.compile(
    r"<R>|<INTRO>|<OUTRO>|<ITEM\s+id=\"[^\"<>\\]*\"(?:\s+group=\"[^\"<>\\]*\")?\s*>"
)


def _validate_recommendation_text(
    value: str,
    *,
    raw_output: str,
    max_chars: int,
    field_name: str,
) -> str:
    text = value.strip()
    validate_mobile_visible_reply(
        text,
        raw_output=raw_output,
        enforce_length=True,
        max_chars=max_chars,
        field_name=field_name,
    )
    return text


def parse_recommendation_marker(
    marker_text: str,
    *,
    raw_output: str,
    candidate_ids: set[str],
    candidate_groups: list[dict],
) -> ParsedRecommendation:
    if not marker_text.startswith("<R>"):
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "<R> 不允许包含属性。",
            raw_output=raw_output,
        )

    group_product_ids, require_group = recommend_group_context(candidate_groups)
    intro = ""
    outro: str | None = None
    items: list[RecommendationItem] = []

    matches = list(RECOMMEND_START_TAG_RE.finditer(marker_text))
    if not matches or matches[0].group(0) != "<R>" or matches[0].start() != 0:
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "推荐块必须以 <R> 开始。",
            raw_output=raw_output,
        )
    if len(matches) == 1 and marker_text[len("<R>") :].strip():
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "<R> 后必须先输出 <INTRO>。",
            raw_output=raw_output,
        )
    invalid_tags = [
        token
        for token in re.findall(r"</?[A-Z]+(?:\s[^<>]*)?>", marker_text)
        if token not in {match.group(0) for match in matches}
    ]
    if invalid_tags:
        error_type = (
            "recommend_marker_invalid_attr"
            if any(tag.startswith("<ITEM") for tag in invalid_tags)
            else "recommend_marker_invalid"
        )
        raise RecoverableAgentError(
            error_type,
            "推荐块包含不再支持的闭合标签、未知标签或非法 <ITEM> 属性。",
            raw_output=raw_output,
            details={"invalid_tags": invalid_tags},
        )

    for index, match in enumerate(matches):
        tag = match.group(0)
        text_start = match.end()
        text_end = matches[index + 1].start() if index + 1 < len(matches) else len(marker_text)
        body = marker_text[text_start:text_end]

        if tag == "<R>":
            if body.strip():
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<R> 后必须先输出 <INTRO>。",
                    raw_output=raw_output,
                    details={"text": body.strip()},
                )
            continue

        if tag == "<INTRO>":
            if intro:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<INTRO> 只能出现一次。",
                    raw_output=raw_output,
                )
            if items or outro is not None:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<INTRO> 必须位于所有 <ITEM> 之前。",
                    raw_output=raw_output,
                )
            intro = _validate_recommendation_text(
                body,
                raw_output=raw_output,
                max_chars=RECOMMEND_FIELD_LIMITS["INTRO"],
                field_name="INTRO",
            )
            continue

        if tag.startswith("<ITEM "):
            if not intro:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<ITEM> 必须位于 <INTRO> 之后。",
                    raw_output=raw_output,
                )
            if outro is not None:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<ITEM> 不能出现在 <OUTRO> 之后。",
                    raw_output=raw_output,
                )
            product_id, group = parse_item_open_tag(tag, raw_output=raw_output)
            validate_item_membership(
                product_id,
                group,
                raw_output=raw_output,
                candidate_ids=candidate_ids,
                group_product_ids=group_product_ids,
                require_group=require_group,
            )
            reason = _validate_recommendation_text(
                body,
                raw_output=raw_output,
                max_chars=RECOMMEND_FIELD_LIMITS["REASON"],
                field_name="REASON",
            )
            if not reason:
                raise RecoverableAgentError(
                    "recommend_marker_empty_reason",
                    "<ITEM> 后的推荐理由不能为空。",
                    raw_output=raw_output,
                    details={"product_id": product_id},
                )
            items.append(RecommendationItem(product_id=product_id, reason=reason, group=group))
            continue

        if tag == "<OUTRO>":
            if not items:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<OUTRO> 必须位于所有 <ITEM> 之后。",
                    raw_output=raw_output,
                )
            if outro is not None:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<OUTRO> 只能出现一次。",
                    raw_output=raw_output,
                )
            outro = body.strip()
            if outro:
                outro = _validate_recommendation_text(
                    body,
                    raw_output=raw_output,
                    max_chars=RECOMMEND_FIELD_LIMITS["OUTRO"],
                    field_name="OUTRO",
                )
            continue

        if tag.startswith("</") or tag == "<REASON>":
            raise RecoverableAgentError(
                "recommend_marker_invalid",
                "推荐块只允许使用 <R>、<INTRO>、<ITEM ...> 和 <OUTRO> 起始标签。",
                raw_output=raw_output,
                details={"tag": tag},
            )

    if not intro:
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "<INTRO> 不能为空且必须位于推荐块开头。",
            raw_output=raw_output,
        )
    if not items:
        raise RecoverableAgentError(
            "recommend_marker_empty",
            "<R> 中至少需要包含一个 <ITEM>。",
            raw_output=raw_output,
        )
    return ParsedRecommendation(intro=intro, items=items, outro=outro)


def recommendation_visible_text(recommendation: ParsedRecommendation) -> str:
    parts = [recommendation.intro]
    parts.extend(item.reason for item in recommendation.items)
    if recommendation.outro:
        parts.append(recommendation.outro)
    return "\n".join(part for part in parts if part.strip())
