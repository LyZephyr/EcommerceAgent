"""<R> 推荐标记解析与统一校验。"""

from __future__ import annotations

import xml.etree.ElementTree as ET

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


def ensure_whitespace_only(
    value: str | None,
    *,
    raw_output: str,
    location: str,
) -> None:
    if value and value.strip():
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "推荐标签内不允许出现未包裹在 INTRO、REASON 或 OUTRO 中的正文。",
            raw_output=raw_output,
            details={"location": location, "text": value.strip()},
        )


def parse_recommendation_item(
    item_el: ET.Element,
    *,
    raw_output: str,
    candidate_ids: set[str],
    group_product_ids: dict[str, set[str]],
    require_group: bool,
) -> RecommendationItem:
    unknown_attrs = sorted(set(item_el.attrib) - {"id", "group"})
    if unknown_attrs:
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "<ITEM> 只允许 id 和 group 属性。",
            raw_output=raw_output,
            details={"unknown_attrs": unknown_attrs},
        )
    product_id = (item_el.attrib.get("id") or "").strip()
    group = (item_el.attrib.get("group") or "").strip() or None
    validate_item_attributes(product_id, group, raw_output=raw_output)
    validate_item_membership(
        product_id,
        group,
        raw_output=raw_output,
        candidate_ids=candidate_ids,
        group_product_ids=group_product_ids,
        require_group=require_group,
    )

    ensure_whitespace_only(item_el.text, raw_output=raw_output, location="ITEM.text")
    reason_children = [child for child in list(item_el) if child.tag == "REASON"]
    other_children = [child.tag for child in list(item_el) if child.tag != "REASON"]
    if other_children:
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "<ITEM> 内只允许出现一个 <REASON>，不能嵌套其他推荐标签。",
            raw_output=raw_output,
            details={"nested_tags": other_children},
        )
    if len(reason_children) != 1:
        raise RecoverableAgentError(
            "recommend_marker_invalid_reason",
            "每个 <ITEM> 内必须且只能有一个 <REASON>。",
            raw_output=raw_output,
            details={"reason_count": len(reason_children)},
        )
    reason_el = reason_children[0]
    if reason_el.attrib or list(reason_el):
        raise RecoverableAgentError(
            "recommend_marker_invalid_reason",
            "<REASON> 不允许包含属性或嵌套标签。",
            raw_output=raw_output,
        )
    ensure_whitespace_only(
        reason_el.tail,
        raw_output=raw_output,
        location="REASON.tail",
    )
    reason = (reason_el.text or "").strip()
    if not reason:
        raise RecoverableAgentError(
            "recommend_marker_empty_reason",
            "<REASON> 不能为空。",
            raw_output=raw_output,
            details={"product_id": product_id},
        )
    validate_mobile_visible_reply(
        reason,
        raw_output=raw_output,
        enforce_length=True,
        max_chars=RECOMMEND_FIELD_LIMITS["REASON"],
        field_name="REASON",
    )
    return RecommendationItem(product_id=product_id, reason=reason, group=group)


def parse_recommendation_marker(
    marker_text: str,
    *,
    raw_output: str,
    candidate_ids: set[str],
    candidate_groups: list[dict],
) -> ParsedRecommendation:
    try:
        root = ET.fromstring(marker_text)
    except ET.ParseError as exc:
        raise RecoverableAgentError(
            "recommend_marker_invalid_xml",
            f"<R> 推荐块不是合法固定标签结构：{exc}",
            raw_output=raw_output,
            details={"exception_type": type(exc).__name__},
        ) from exc

    if root.tag != "R":
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "推荐块根标签必须是 <R>。",
            raw_output=raw_output,
            details={"actual_tag": root.tag},
        )
    if root.attrib:
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "<R> 不允许包含属性。",
            raw_output=raw_output,
            details={"attributes": sorted(root.attrib)},
        )
    ensure_whitespace_only(root.text, raw_output=raw_output, location="R.text")

    group_product_ids, require_group = recommend_group_context(candidate_groups)
    seen_intro = False
    seen_item = False
    seen_outro = False
    intro = ""
    outro: str | None = None
    items: list[RecommendationItem] = []

    for child in list(root):
        if child.tag not in {"INTRO", "ITEM", "OUTRO"}:
            raise RecoverableAgentError(
                "recommend_marker_invalid",
                "<R> 内只允许出现 INTRO、ITEM 和 OUTRO 标签。",
                raw_output=raw_output,
                details={"actual_tag": child.tag},
            )
        ensure_whitespace_only(
            child.tail,
            raw_output=raw_output,
            location=f"{child.tag}.tail",
        )

        if child.tag == "INTRO":
            if seen_intro:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<INTRO> 只能出现一次。",
                    raw_output=raw_output,
                )
            if seen_item or seen_outro:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<INTRO> 必须位于所有 <ITEM> 之前。",
                    raw_output=raw_output,
                )
            if child.attrib or list(child):
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<INTRO> 不允许包含属性或嵌套标签。",
                    raw_output=raw_output,
                )
            intro = (child.text or "").strip()
            validate_mobile_visible_reply(
                intro,
                raw_output=raw_output,
                enforce_length=True,
                max_chars=RECOMMEND_FIELD_LIMITS["INTRO"],
                field_name="INTRO",
            )
            seen_intro = True
        elif child.tag == "ITEM":
            if seen_outro:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<ITEM> 不能出现在 <OUTRO> 之后。",
                    raw_output=raw_output,
                )
            item = parse_recommendation_item(
                child,
                raw_output=raw_output,
                candidate_ids=candidate_ids,
                group_product_ids=group_product_ids,
                require_group=require_group,
            )
            items.append(item)
            seen_item = True
        elif child.tag == "OUTRO":
            if seen_outro:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<OUTRO> 只能出现一次。",
                    raw_output=raw_output,
                )
            if not seen_item:
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<OUTRO> 必须位于所有 <ITEM> 之后。",
                    raw_output=raw_output,
                )
            if child.attrib or list(child):
                raise RecoverableAgentError(
                    "recommend_marker_invalid",
                    "<OUTRO> 不允许包含属性或嵌套标签。",
                    raw_output=raw_output,
                )
            outro_text = (child.text or "").strip()
            if outro_text:
                validate_mobile_visible_reply(
                    outro_text,
                    raw_output=raw_output,
                    enforce_length=True,
                    max_chars=RECOMMEND_FIELD_LIMITS["OUTRO"],
                    field_name="OUTRO",
                )
            outro = outro_text
            seen_outro = True

    if not seen_intro or not intro:
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
