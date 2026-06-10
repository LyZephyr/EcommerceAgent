"""商品检索工具：将 LLM 的工具调用参数转为 retriever.retrieve() 调用。"""

from __future__ import annotations

import json

from openai import AsyncOpenAI

from config import ARK_API_KEY, ARK_BASE_URL, ARK_MODEL, TOP_K
from retriever import retrieve

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "retrieve_products",
        "description": (
            "根据用户的一个或多个购物需求，从商品库中检索相关商品。\n\n"
            "调用规则：\n"
            "- requests: 检索子需求列表；普通推荐只填 1 个 request，场景化组合推荐可拆成 2-4 个 request\n"
            "- label: 子需求名称，如 防晒护肤、度假穿搭、通勤数码\n"
            "- search_query: 将口语化需求改写为包含品类名和属性关键词的检索语句，只写正向需求（无糖，无酒精等也属于正向需求）\n"
            "- must_have_terms: 用户明确要求的品牌/规格/功能/属性/场景/口味等（价格除外）\n"
            "- exclude_terms: 否定约束，用户明确要求排除的商品品牌、属性（无糖/无酒精等对应的负向约束为：含糖/含酒精）等\n"
            "- exclude_brands: 需排除的具体品牌名\n"
            "- category: 能确定类目时必须填写；跨类目场景应拆成多个带 category 的 request\n"
            "- 价格：每个 request 独立填写。「以内/以下」只填 max_price；「以上/不低于」只填 min_price；"
            "「左右/出头」适当放宽（如一千左右 -> min_price=700, max_price=1300）\n\n"
            "可用类目：服饰运动、美妆护肤、数码电子、食品饮料"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "requests": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "description": "一个或多个独立检索子需求",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "子需求名称，如 '防晒护肤'",
                            },
                            "search_query": {
                                "type": "string",
                                "description": "改写后的检索语句，如 '手机 国产 性价比高 续航久'",
                            },
                            "category": {
                                "type": "string",
                                "description": "商品类目",
                                "enum": ["服饰运动", "美妆护肤", "数码电子", "食品饮料"],
                            },
                            "min_price": {"type": "number", "description": "最低价格"},
                            "max_price": {"type": "number", "description": "最高价格"},
                            "must_have_terms": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "必须具备的属性关键词",
                            },
                            "exclude_terms": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "需排除的属性短语",
                            },
                            "exclude_brands": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "需排除的品牌",
                            },
                        },
                        "required": ["label", "search_query"],
                    },
                },
            },
            "required": ["requests"],
        },
    },
}


def execute(arguments: dict) -> list[dict]:
    """执行一组商品检索，返回按 request 分组的 Top-K 商品。"""
    groups = []
    for request in arguments["requests"]:
        intent = _request_to_intent(request)
        products = retrieve(request["search_query"], TOP_K, intent)
        groups.append(
            {
                "label": request["label"],
                "search_query": request["search_query"],
                "products": products,
            }
        )
    return groups


async def parse_intent(query: str) -> dict:
    """通过强制工具调用提取检索意图（供离线评估使用）。"""
    from agent import EVAL_INTENT_ADDENDUM, SYSTEM_PROMPT

    client = AsyncOpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)
    response = await client.chat.completions.create(
        model=ARK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + EVAL_INTENT_ADDENDUM},
            {"role": "user", "content": query},
        ],
        tools=[TOOL_DEFINITION],
        tool_choice={"type": "function", "function": {"name": "retrieve_products"}},
        temperature=0.3,
    )
    msg = response.choices[0].message
    if not msg.tool_calls:
        return {"rewritten_query": query}
    try:
        arguments = json.loads(msg.tool_calls[0].function.arguments)
    except (json.JSONDecodeError, TypeError):
        return {"rewritten_query": query}
    requests = arguments.get("requests")
    if not requests:
        return {"rewritten_query": query}
    return _request_to_intent(requests[0])


def _request_to_intent(request: dict) -> dict:
    return {
        "rewritten_query": request.get("search_query") or "",
        "category": request.get("category"),
        "min_price": request.get("min_price"),
        "max_price": request.get("max_price"),
        "must_have_terms": request.get("must_have_terms", []),
        "exclude_terms": request.get("exclude_terms", []),
        "exclude_brands": request.get("exclude_brands", []),
    }
