"""LLM 意图解析模块：从用户查询中提取结构化购物意图并改写检索 query。"""

from __future__ import annotations

import json

from openai import AsyncOpenAI

from config import ARK_API_KEY, ARK_BASE_URL, ARK_MODEL

INTENT_PROMPT = """\
你是电商搜索意图解析器。分析用户的购物查询，输出结构化 JSON。

可用商品类目（只能选其中之一，不确定则留空字符串）：服饰运动、美妆护肤、数码电子、食品饮料

严格按以下 JSON 格式输出，不要输出任何其他内容：
{
  "rewritten_query": "将用户口语改写为包含具体品类名和属性关键词的检索语句",
  "category": "类目名或空字符串",
  "min_price": null或数字,
  "max_price": null或数字,
  "exclude_brands": [],
  "negative_constraints": []
}

示例：
用户：推荐一款适合夏天穿的上衣
{"rewritten_query":"夏季 短袖T恤 上衣 透气 速干 清凉 凉感","category":"服饰运动","min_price":null,"max_price":null,"exclude_brands":[],"negative_constraints":[]}

用户：200元以下的蓝牙耳机
{"rewritten_query":"蓝牙耳机 无线耳机 降噪 音质","category":"数码电子","min_price":null,"max_price":200,"exclude_brands":[],"negative_constraints":[]}

用户：推荐防晒霜，不要日系品牌
{"rewritten_query":"防晒霜 防晒 SPF 隔离 防紫外线 清爽不油腻","category":"美妆护肤","min_price":null,"max_price":null,"exclude_brands":["资生堂","安耐晒","花王","佳丽宝"],"negative_constraints":["日系品牌"]}

用户：打完球想喝点冰的
{"rewritten_query":"运动饮料 冰饮 气泡水 解渴 清爽 功能饮料 电解质","category":"食品饮料","min_price":null,"max_price":null,"exclude_brands":[],"negative_constraints":[]}"""


async def parse_intent(query: str) -> dict:
    """调用 LLM 解析用户购物意图，返回结构化 dict。解析失败时回退为仅含 rewritten_query 的最小结果。"""
    client = AsyncOpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)
    response = await client.chat.completions.create(
        model=ARK_MODEL,
        messages=[
            {"role": "system", "content": INTENT_PROMPT},
            {"role": "user", "content": query},
        ],
        temperature=0,
    )
    content = (response.choices[0].message.content or "").strip()
    content = _strip_code_fence(content)
    try:
        intent = json.loads(content)
        if not isinstance(intent.get("rewritten_query"), str) or not intent["rewritten_query"]:
            intent["rewritten_query"] = query
        return intent
    except (json.JSONDecodeError, TypeError):
        return {"rewritten_query": query}


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text
