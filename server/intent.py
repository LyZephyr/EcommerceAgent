"""LLM 意图解析模块：从用户查询中提取结构化购物意图并改写检索 query。"""

from __future__ import annotations

import json

from openai import AsyncOpenAI

from config import ARK_API_KEY, ARK_BASE_URL, ARK_MODEL

_INTENT_FIELDS = {
    "rewritten_query",
    "category",
    "min_price",
    "max_price",
    "must_have_terms",
    "exclude_terms",
    "exclude_brands",
}

INTENT_PROMPT = """\
你是电商搜索意图解析器。分析用户的购物查询，输出结构化 JSON。

可用商品类目（只能选其中之一，不确定则留空字符串）：服饰运动、美妆护肤、数码电子、食品饮料

严格按以下 JSON 格式输出，不要输出任何其他内容：
{
  "rewritten_query": "将用户口语改写为包含具体品类名和属性关键词的检索语句",
  "category": "类目名或空字符串",
  "min_price": null或数字,
  "max_price": null或数字,
  "must_have_terms": [],
  "exclude_terms": [],
  "exclude_brands": []
}

规则：
1. rewritten_query 只写用户正向想要的品类、场景、功能、规格和属性，不要包含否定约束。
2. 明确要求的品牌、商品规格、功能、属性、容量、尺寸、口味、使用场景等等都写入 must_have_terms。
3. "无糖/0糖/零糖/无酒精/不含香精/不含添加剂/未添加防腐剂" 这类是用户想要的正向属性，写入 must_have_terms，不要把"糖/酒精/香精/添加剂/防腐剂"单独写入 exclude_terms。
4. "不要/不想/别/非/除了" 等否定约束后的品牌、品类、规格、功能、属性等写入 exclude_terms；exclude_terms 要写成明确违规短语，如"含糖","添加糖","含添加剂","含酒精","折叠屏","贴片式面膜"，不要写"糖","添加剂","酒精"这类裸词；明确品牌也同步写入 exclude_brands。
5. "以内/以下/不超过" 只填写 max_price；"以上/不低于" 只填写 min_price。
6. "左右/出头/附近" 要适当放宽筛选条件。例如 "一千左右" 输出 min_price=700, max_price=1300；"三千出头" 输出 min_price=3000, max_price=4000。

示例：
用户：推荐一款适合夏天穿的上衣
{"rewritten_query":"夏季 短袖T恤 上衣 透气 速干 清凉 凉感","category":"服饰运动","min_price":null,"max_price":null,"must_have_terms":["夏季","短袖T恤","透气","清凉"],"exclude_terms":[],"exclude_brands":[]}

用户：200元以下的蓝牙耳机
{"rewritten_query":"蓝牙耳机 无线耳机 降噪 音质","category":"数码电子","min_price":null,"max_price":200,"must_have_terms":["蓝牙耳机","无线耳机"],"exclude_terms":[],"exclude_brands":[]}

用户：推荐防晒霜，不要日系品牌
{"rewritten_query":"防晒霜 防晒 SPF 隔离 防紫外线 清爽不油腻","category":"美妆护肤","min_price":null,"max_price":null,"must_have_terms":["防晒霜","防晒","清爽"],"exclude_terms":["日系品牌","资生堂","安耐晒","花王","佳丽宝"],"exclude_brands":["资生堂","安耐晒","花王","佳丽宝"]}

用户：打完球想喝点冰的
{"rewritten_query":"运动饮料 冰饮 气泡水 解渴 清爽 功能饮料 电解质","category":"食品饮料","min_price":null,"max_price":null,"must_have_terms":["冰饮","解渴","运动饮料","电解质"],"exclude_terms":[],"exclude_brands":[]}

用户：推荐一款旗舰手机，不要折叠屏的
{"rewritten_query":"旗舰智能手机 高性能 旗舰芯片 直屏 稳定耐用","category":"数码电子","min_price":null,"max_price":null,"must_have_terms":["旗舰手机","高性能","旗舰芯片","直屏"],"exclude_terms":["折叠屏"],"exclude_brands":[]}

用户：一千左右的实战篮球鞋
{"rewritten_query":"实战篮球鞋 缓震 支撑 防滑 耐磨 专业比赛","category":"服饰运动","min_price":700,"max_price":1300,"must_have_terms":["实战篮球鞋","缓震","支撑","防滑"],"exclude_terms":[],"exclude_brands":[]}

用户：不想喝气泡饮料，有没有茶饮或功能饮料
{"rewritten_query":"茶饮 功能饮料 解渴 清爽 提神 补充能量","category":"食品饮料","min_price":null,"max_price":null,"must_have_terms":["茶饮","功能饮料","解渴"],"exclude_terms":["气泡饮料","碳酸饮料","汽水"],"exclude_brands":[]}

用户：想喝无糖饮料
{"rewritten_query":"饮料 清爽 解渴 茶饮 功能饮料","category":"食品饮料","min_price":null,"max_price":null,"must_have_terms":["无糖","0糖","零糖"],"exclude_terms":[],"exclude_brands":[]}"""


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
        intent = {key: intent.get(key) for key in _INTENT_FIELDS}
        if not isinstance(intent.get("rewritten_query"), str) or not intent["rewritten_query"]:
            intent["rewritten_query"] = query
        for key in ("must_have_terms", "exclude_terms", "exclude_brands"):
            value = intent.get(key)
            intent[key] = value if isinstance(value, list) else []
        return intent
    except (json.JSONDecodeError, TypeError):
        return {"rewritten_query": query}


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text
