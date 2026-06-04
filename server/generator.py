"""LLM 对话生成模块：调用 Doubao API，基于检索上下文生成流式回复。"""

import json
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from config import ARK_API_KEY, ARK_BASE_URL, ARK_MODEL


SYSTEM_PROMPT = """\
你是一个专业、克制的电商导购助手。
必须只基于提供的商品资料回答，不要编造不存在的商品、价格、功效、优惠或库存。
如果资料不能满足用户需求，要直接说明没有足够匹配的商品，并给出可继续筛选的方向。
回答要自然简洁，推荐时说明理由、适合人群和需要注意的评价反馈。

重要格式要求：你的回复必须以一行推荐标记开头，格式为 <R>商品ID1,商品ID2</R>
只包含你真正推荐给用户的商品ID，不要包含不相关的商品。
如果没有合适的商品可推荐，输出 <R></R>
标记之后换行，再写给用户看的自然语言回复。用户看不到这个标记。"""


async def generate_stream(query: str, context: list[dict]) -> AsyncIterator[str]:
    """
    将用户 query 和检索到的商品上下文组装为 prompt，
    调用 Doubao API 流式生成回复，逐 token yield。
    """
    if not ARK_API_KEY:
        raise RuntimeError("缺少 ARK_API_KEY，请在项目根目录 .env 中配置豆包 Ark API Key。")

    client = AsyncOpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)
    stream = await client.chat.completions.create(
        model=ARK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(query, context)},
        ],
        temperature=0.3,
        stream=True,
    )

    async for chunk in stream:
        token = chunk.choices[0].delta.content
        if token:
            yield token


def _build_user_prompt(query: str, context: list[dict]) -> str:
    products = [
        {
            "product_id": product.get("product_id"),
            "title": product.get("title"),
            "brand": product.get("brand"),
            "category": product.get("category"),
            "sub_category": product.get("sub_category"),
            "price": product.get("price"),
            "min_price": product.get("min_price"),
            "max_price": product.get("max_price"),
            "document": product.get("document"),
        }
        for product in context
    ]
    product_context = json.dumps(products, ensure_ascii=False, indent=2)
    return f"""用户需求：
{query}

检索到的候选商品资料：
{product_context}

请先输出 <R>你推荐的商品ID</R> 标记，然后换行写自然语言回复。"""
