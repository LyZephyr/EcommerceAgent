"""Agent 编排：ReAct 工具循环 + 最终回复解析。

流程：
1. LLM 接收对话历史 + 工具定义，决定调用工具还是直接回复
2. 工具结果回填给 LLM，最多执行 3 步工具调用
3. 最终回复解析商品推荐、结构化对比和购物车事件
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from openai import AsyncOpenAI

import conversation
from config import ARK_API_KEY, ARK_BASE_URL, ARK_MODEL
from tools import TOOL_DEFINITIONS, execute as execute_tool

SYSTEM_PROMPT = """\
你是一个专业、克制的电商导购助手。

## 工具使用规则
- 当用户有新的商品推荐、搜索或筛选需求时，调用 retrieve_products 工具检索商品库
- 当用户明确要求加购、删除、改数量、查看或清空购物车时，调用对应购物车工具
- 加购工具必须使用明确的 product_ids。批量检索、批量加购等需求应尽量使用批量参数一次完成，不要用单参数重复调用多次工具
- 当对话过长导致你无法确定用户指代的历史商品时，可以调用 list_recent_products 补充记忆；如果用户表达本身含糊（如“这个”“那个”无法定位），必须先追问，不要调用工具猜测
- 删除和改数量中的“第一个”“第二个”优先指向购物车明细
- 购物车指代不明确时必须先反问，不要猜测用户想操作哪款商品
- 当用户追问之前已推荐商品的细节或对比时，基于对话历史直接回答，不需要重新检索
- 当用户需求过于模糊、缺少关键偏好时，先反问用户以明确需求方向，不要直接检索
- 当用户描述一个需要多类商品的场景化组合需求时，将场景拆成多个检索子需求，并在一次 retrieve_products 工具调用中填写多个 requests
- 寒暄或与购物无关的问题，直接简短回复

## 回复规则
- 只基于工具返回的商品资料回答，不编造不存在的商品、价格、功效、优惠或库存
- 价格、库存、上下架和优惠只能引用工具返回字段；没有字段时不要自行推断
- 不编造购物车中不存在的商品、价格、优惠、库存或配送承诺
- 推荐时说明理由、适合人群和需要注意的评价反馈
- 对比多个商品时，按照用户关心的维度进行对比，如果用户没有说明从哪些方面进行对比，则默认按价格、核心卖点、适合人群、评价反馈和注意事项等维度整合，不直接堆叠原始资料
- 回答自然简洁"""

_MAX_TOOL_STEPS = 3

EVAL_INTENT_ADDENDUM = """

## 离线评估说明（仅本次调用生效）
- 本次为单条检索 query 的离线评估，必须调用 retrieve_products，且 requests 中只填写 1 个 request
- 输入均为明确的商品推荐或搜索需求，直接检索即可，无需反问或调用购物车工具"""

_GENERATION_ADDENDUM = """

## 格式要求（仅本次回复生效）
回复必须以一行推荐标记开头：<R>商品ID1,商品ID2</R>
只包含你真正推荐的商品 ID。没有合适商品时输出 <R></R>
只要商品资料中存在可用候选，就必须至少推荐 1 个商品；场景化组合推荐优先覆盖不同子需求。
如果本次回复是多商品对比，可在推荐标记后追加一行结构化对比标记：
<C>{"products":[{"product_id":"商品ID","title":"商品名"}],"rows":[{"dimension":"价格","values":{"商品ID":"对比值"}}]}</C>
没有结构化对比表时不要输出 <C> 标记。
标记后换行，必须写给用户的自然语言回复；即使没有合适商品，也要说明原因。用户看不到此标记。"""

_DIRECT_COMPARE_INSTRUCTION = """

## 结构化对比事件
当你不调用工具、直接基于历史商品回答多商品对比时，可以先输出一行结构化对比标记：
<C>{"products":[{"product_id":"商品ID","title":"商品名"}],"rows":[{"dimension":"价格","values":{"商品ID":"对比值"}}]}</C>
随后输出给用户看的自然语言结论。非对比回复不要输出 <C> 标记。"""


@dataclass
class TokenEvent:
    content: str


@dataclass
class ProductEvent:
    product_id: str
    product_data: dict


@dataclass
class StatusEvent:
    status: str


@dataclass
class CompareEvent:
    payload: dict


@dataclass
class CartEvent:
    payload: dict


async def run_turn(
    conversation_id: str,
    user_message: str,
) -> AsyncIterator[TokenEvent | ProductEvent | StatusEvent | CompareEvent | CartEvent]:
    """执行一轮对话，yield TokenEvent / ProductEvent / StatusEvent。"""
    if not ARK_API_KEY:
        raise RuntimeError(
            "缺少 ARK_API_KEY，请在项目根目录 .env 中配置正确的 API Key。"
        )

    conversation.append(conversation_id, {"role": "user", "content": user_message})
    history = conversation.get_history(conversation_id)

    client = AsyncOpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + _DIRECT_COMPARE_INSTRUCTION,
        }
    ] + history
    candidates_by_id: dict[str, dict] = {}
    used_retrieve_tool = False
    generation_instruction_added = False

    for _ in range(_MAX_TOOL_STEPS):
        response = await client.chat.completions.create(
            model=ARK_MODEL,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            temperature=0.3,
        )
        assistant_msg = response.choices[0].message

        if not assistant_msg.tool_calls:
            _append_final_response(
                conversation_id,
                assistant_msg.content or "",
                used_retrieve_tool,
            )
            async for event in _events_from_final_response(
                assistant_msg.content or "",
                candidates_by_id,
                used_retrieve_tool,
            ):
                yield event
            return

        tool_call_msg = _tool_call_message(assistant_msg.tool_calls)
        messages.append(tool_call_msg)
        conversation.append(conversation_id, tool_call_msg)

        retrieve_tool_used_this_step = False
        for tool_call in assistant_msg.tool_calls:
            arguments = json.loads(tool_call.function.arguments or "{}")
            tool_name = tool_call.function.name

            if _is_retrieve_tool(tool_name):
                yield StatusEvent("正在检索商品...")
                candidate_groups = execute_tool(tool_name, arguments)
                used_retrieve_tool = True
                retrieve_tool_used_this_step = True
                candidates_by_id.update(
                    {
                        product["product_id"]: product
                        for product in _flatten_candidate_groups(candidate_groups)
                    }
                )
                tool_content = _format_candidate_groups(candidate_groups)
                history_content = _format_candidate_groups_compact(candidate_groups)
            elif _is_cart_tool(tool_name):
                yield StatusEvent(_cart_status(tool_name))
                result = execute_tool(tool_name, arguments, conversation_id)
                if result.get("success") and result.get("cart"):
                    yield CartEvent(result["cart"])
                tool_content = json.dumps(result, ensure_ascii=False)
                history_content = tool_content
            else:
                result = execute_tool(tool_name, arguments)
                tool_content = json.dumps(result, ensure_ascii=False)
                history_content = tool_content

            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_content,
            }
            messages.append(tool_msg)
            conversation.append(
                conversation_id,
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": history_content,
                },
            )
        if retrieve_tool_used_this_step and not generation_instruction_added:
            messages.append({"role": "system", "content": _GENERATION_ADDENDUM})
            generation_instruction_added = True

    response = await client.chat.completions.create(
        model=ARK_MODEL,
        messages=messages
        + [
            {
                "role": "system",
                "content": "工具调用次数已达上限，请基于已有工具结果直接回复用户；如果信息仍不足，请追问用户。",
            }
        ],
        temperature=0.3,
    )
    content = response.choices[0].message.content or ""
    _append_final_response(
        conversation_id,
        content,
        used_retrieve_tool,
    )
    async for event in _events_from_final_response(
        content,
        candidates_by_id,
        used_retrieve_tool,
    ):
        yield event


def _tool_call_message(tool_calls) -> dict:
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in tool_calls
        ],
    }


def _append_final_response(
    conversation_id: str,
    content: str,
    used_retrieve_tool: bool,
) -> None:
    if used_retrieve_tool:
        _, _, clean_text = _strip_generation_hidden_prefix(content)
    else:
        _, clean_text = _extract_compare_tag(content)
    if not clean_text.strip():
        raise RuntimeError(f"LLM 生成了空的可见回复：{content!r}")
    conversation.append(
        conversation_id,
        {"role": "assistant", "content": clean_text.strip()},
    )


async def _events_from_final_response(
    content: str,
    candidates_by_id: dict[str, dict],
    used_retrieve_tool: bool,
) -> AsyncIterator[ProductEvent | CompareEvent | TokenEvent]:
    if used_retrieve_tool:
        recommended_ids, compare_payload, clean_text = _strip_generation_hidden_prefix(
            content
        )
        for pid in recommended_ids:
            if pid in candidates_by_id:
                yield ProductEvent(pid, candidates_by_id[pid])
        if compare_payload:
            yield CompareEvent(compare_payload)
        if clean_text.strip():
            yield TokenEvent(clean_text)
        return

    compare_payload, clean_text = _extract_compare_tag(content)
    if compare_payload:
        yield CompareEvent(compare_payload)
    yield TokenEvent(clean_text)


def _flatten_candidate_groups(candidate_groups: list[dict]) -> list[dict]:
    candidates = []
    seen_ids = set()
    for group in candidate_groups:
        for product in group.get("products", []):
            product_id = product["product_id"]
            if product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            candidates.append(product)
    return candidates


def _is_cart_tool(tool_name: str) -> bool:
    return tool_name in {
        "add_to_cart",
        "list_recent_products",
        "remove_from_cart",
        "update_cart_item",
        "view_cart",
        "clear_cart",
    }


def _is_retrieve_tool(tool_name: str) -> bool:
    return tool_name == "retrieve_products"


def _cart_status(tool_name: str) -> str:
    if tool_name == "list_recent_products":
        return "正在读取近期商品..."
    return "正在更新购物车..."


def _format_candidate_groups(candidate_groups: list[dict]) -> str:
    """完整格式，用于当前轮次的 LLM 生成。"""
    groups = [
        {
            "label": group.get("label"),
            "search_query": group.get("search_query"),
            "products": [
                {
                    "product_id": p.get("product_id"),
                    "title": p.get("title"),
                    "brand": p.get("brand"),
                    "category": p.get("category"),
                    "sub_category": p.get("sub_category"),
                    "price": p.get("price"),
                    "stock": p.get("stock"),
                    "image_url": p.get("image_url"),
                    "document": p.get("document"),
                }
                for p in group.get("products", [])
            ],
        }
        for group in candidate_groups
    ]
    return json.dumps(groups, ensure_ascii=False, indent=2)


def _format_candidate_groups_compact(candidate_groups: list[dict]) -> str:
    """紧凑格式，存入历史上下文，不含完整 document。"""
    groups = [
        {
            "label": group.get("label"),
            "products": [
                {
                    "product_id": p.get("product_id"),
                    "title": p.get("title"),
                    "brand": p.get("brand"),
                    "category": p.get("category"),
                    "price": p.get("price"),
                    "stock": p.get("stock"),
                }
                for p in group.get("products", [])
            ],
        }
        for group in candidate_groups
    ]
    return json.dumps(groups, ensure_ascii=False)


def _extract_generation_hidden_prefix(
    text: str,
    *,
    final: bool = False,
) -> tuple[list[str], dict | None, str] | None:
    recommend_match = re.search(r"<R>(.*?)</R>\n?", text, flags=re.DOTALL)
    if not recommend_match:
        return None

    recommended_ids = _parse_recommend_ids(recommend_match.group(1))
    after_recommend = text[recommend_match.end() :]
    stripped_after = after_recommend.lstrip()
    leading_whitespace = after_recommend[: len(after_recommend) - len(stripped_after)]

    if stripped_after.startswith("<C>"):
        compare_match = re.match(r"<C>(.*?)</C>\n?", stripped_after, flags=re.DOTALL)
        if not compare_match:
            return None
        compare_payload = _loads_compare_payload(compare_match.group(1))
        remainder = text[: recommend_match.start()] + leading_whitespace + stripped_after[compare_match.end() :]
        return recommended_ids, compare_payload, remainder

    if stripped_after and "<C>".startswith(stripped_after):
        return None

    if not stripped_after and not final:
        return None

    remainder = text[: recommend_match.start()] + after_recommend
    return recommended_ids, None, remainder


def _strip_generation_hidden_prefix(text: str) -> tuple[list[str], dict | None, str]:
    hidden_prefix = _extract_generation_hidden_prefix(text, final=True)
    if hidden_prefix:
        return hidden_prefix
    return [], None, text


def _extract_compare_tag(text: str) -> tuple[dict | None, str]:
    match = re.search(r"<C>(.*?)</C>\n?", text, flags=re.DOTALL)
    if not match:
        return None, text
    compare_payload = _loads_compare_payload(match.group(1))
    remaining = text[: match.start()] + text[match.end() :]
    return compare_payload, remaining


def _loads_compare_payload(raw_json: str) -> dict | None:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_recommend_ids(ids_str: str) -> list[str]:
    ids_str = ids_str.strip()
    return [pid.strip() for pid in ids_str.split(",") if pid.strip()] if ids_str else []
