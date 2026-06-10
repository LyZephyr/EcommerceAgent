"""Agent 编排：ReAct 工具循环 + 最终回复解析。

流程：
1. LLM 接收对话历史 + 工具定义，决定调用工具还是直接回复
2. 工具结果回填给 LLM，最多执行 3 步工具调用
3. 最终回复解析商品推荐、结构化对比和购物车事件
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import traceback
import xml.etree.ElementTree as ET
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from openai import AsyncOpenAI

import conversation
from config import ARK_API_KEY, ARK_BASE_URL, ARK_MODEL
from tools import TOOL_DEFINITIONS, execute as execute_tool

logger = logging.getLogger(__name__)

TOOL_USE_PROMPT = """\
你是一个专业、克制的电商导购助手。

## 工具使用规则
- 当用户有新的商品推荐、搜索或筛选需求时，调用 retrieve_products 工具检索商品库
- 当用户明确要求加购、删除、改数量、查看或清空购物车时，调用对应购物车工具
- 加购工具必须使用明确的 product_ids，且只能加购当前会话已展示过商品卡片的商品。因此你在推荐回复中口头点名、对比或建议加购的每个商品，其 product_id 都必须写入 <R> 推荐标记，否则用户无法加购
- 批量检索、批量加购等需求应尽量使用批量参数一次完成，不要用单参数重复调用多次工具
- 当对话过长导致你无法确定用户指代的历史商品时，可以调用 list_recent_products 补充记忆；如果用户表达本身含糊（如“这个”“那个”无法定位），必须先追问，不要调用工具猜测
- 删除和改数量中的“第一个”“第二个”优先指向购物车明细
- 购物车指代不明确时必须先反问，不要猜测用户想操作哪款商品
- 当用户追问之前已推荐商品的细节或对比时，基于对话历史直接回答，不需要重新检索
- 当用户需求过于模糊、缺少关键偏好时，先反问用户以明确需求方向，不要直接检索
- 当用户描述一个需要多类商品的场景化组合需求时，将场景拆成多个检索子需求，并在一次 retrieve_products 工具调用中填写多个 requests
- 寒暄或与购物无关的问题，直接简短回复
"""

FINAL_REPLY_PROMPT = """\
## 回复规则
- 只基于工具返回的商品资料回答，不编造不存在的商品、价格、功效、优惠或库存
- 价格、库存、上下架和优惠只能引用工具返回字段；没有字段时不要自行推断
- 不编造购物车中不存在的商品、价格、优惠、库存或配送承诺等
- 推荐时只输出移动端可快速浏览的短结论：先给 1 句总体建议，再给最多 3 条短理由
- 每条短理由不超过 35 个中文字符；不要把商品详情、长卖点、完整注意事项或评价原文堆进正文
- 商品标题、价格、品牌、规格、库存、图片和加购入口由客户端商品卡片展示；正文不要重复罗列这些字段
- 当推荐商品超过 3 个时，只概括推荐逻辑，不要逐个写长段说明
- 对比多个商品时，按照用户关心的维度进行对比；如果用户没有说明维度，则默认按价格、核心卖点、适合人群和注意事项整合
- 对比结论正文最多 3 句，详细对比必须通过 <C> 结构化对比标记承载，不要在正文中输出表格
- 禁止输出 Markdown 标题、Markdown 表格、分隔线、引用块或深层编号列表；不要输出 ###、**、|、--- 等 Markdown 语法符号
- 可以使用普通短句或少量短项目符号，但整段可见正文应控制在 120 个中文字符以内
- 回答自然简洁，优先让商品卡片和结构化对比成为主要信息载体

## 隐藏事件标记
- 当最终回复是商品推荐、搜索结果、筛选结果或场景化组合推荐时，必须只输出一个 <R>...</R> 推荐块；<R> 外不允许有任何非空正文
- 推荐块固定格式：<R><INTRO>短总体建议</INTRO><ITEM id="商品ID"><REASON>短推荐理由</REASON></ITEM><OUTRO>可选短总结</OUTRO></R>
- 跨类目组合推荐时，<ITEM> 必须带 group，且 group 必须等于 retrieve_products 返回的某个 request label；普通单类目推荐不要写 group
- <INTRO> 不超过 40 个中文字符，每个 <REASON> 不超过 45 个中文字符，<OUTRO> 不超过 40 个中文字符
- <ITEM> 的 id 必须来自本轮工具候选；每个 <ITEM> 内必须且只能有一个 <REASON>
- <ITEM> 属性值只允许字母、数字、汉字、-、_、空格、冒号和斜杠；不要写引号、尖括号或反斜杠
- 只要商品资料中存在可用候选，就必须至少推荐 1 个商品；场景化组合推荐优先覆盖不同子需求
- 当用户要求基于当前会话之前已经推荐或展示过的多个商品做对比，且本轮不是新的商品推荐时，必须以一行结构化对比标记开头：
<C>{"products":[{"product_id":"商品ID","title":"商品名"}],"rows":[{"dimension":"价格","values":{"商品ID":"对比值"}}]}</C>
- <R> 和 <C> 不能同时出现在同一条回复中：基于之前推荐过的商品进行对比时只输出 <C>；商品推荐、搜索、筛选或组合推荐时只输出 <R>
- 反问澄清、寒暄、购物车操作回复和普通说明不要输出 <R> 或 <C>
- 用户看不到隐藏标记；不要在推荐正文中重复铺开商品价格、库存、规格、品牌等卡片字段

## 输出示例
普通同类推荐：
<R>
<INTRO>整体建议：日常早餐优先选常温纯牛奶，保存和携带都方便。</INTRO>
<ITEM id="p_food_001">
<REASON>这款容量和口感更均衡，适合家庭长期囤货。</REASON>
</ITEM>
<ITEM id="p_food_002">
<REASON>这款更适合看重低脂负担的用户。</REASON>
</ITEM>
<OUTRO>如果只选一款，优先选更符合饮用频率的那款。</OUTRO>
</R>

跨类目组合推荐：
<R>
<INTRO>整体建议：海边出行先保证防晒，再补一件轻薄外套。</INTRO>
<ITEM id="p_beauty_001" group="防晒护肤">
<REASON>这款适合长时间户外，防晒强度和清爽度更均衡。</REASON>
</ITEM>
<ITEM id="p_clothes_001" group="度假穿搭">
<REASON>这款轻薄好收纳，适合早晚温差和空调环境。</REASON>
</ITEM>
<OUTRO>预算有限时，先买防晒，再补外套。</OUTRO>
</R>

反问澄清：
你更看重控油、保湿，还是温和不刺激？我可以按肤质帮你缩小范围。

对比输出：
<C>{"products":[{"product_id":"p1","title":"商品 A"},{"product_id":"p2","title":"商品 B"}],"rows":[{"dimension":"适合人群","values":{"p1":"日常通勤","p2":"户外运动"}}]}</C>
如果你更看重轻便，优先选商品 A；如果更看重户外强度，选商品 B。"""

SYSTEM_PROMPT = TOOL_USE_PROMPT + "\n" + FINAL_REPLY_PROMPT

_MAX_TOOL_STEPS = 3
_MAX_RECOVERY_RETRIES = 2
_MAX_TOTAL_RECOVERY_ATTEMPTS = 6
_LLM_TIMEOUT_SECONDS = 60
_LOG_ARGUMENTS_MAX_CHARS = 4000
_LOG_TOOL_RESULT_MAX_CHARS = 100
_LOG_LLM_OUTPUT_MAX_CHARS = 4000
_MARKER_TAG_RE = re.compile(r"</?(?:R|C)(?:\s[^>]*)?>")
_MOBILE_VISIBLE_REPLY_MAX_CHARS = 120
_VISIBLE_MARKDOWN_TOKEN_RE = re.compile(r"###|\*\*|\||(^|\n)\s*-{3,}\s*$", re.MULTILINE)
_RECOMMEND_FIELD_LIMITS = {"INTRO": 40, "REASON": 45, "OUTRO": 40}
_ITEM_ATTR_VALUE_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff\-_\s:/]+$")


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


@dataclass
class BlockTextDeltaEvent:
    message_id: str
    block_id: str
    content: str


@dataclass
class BlockProductEvent:
    message_id: str
    block_id: str
    product_id: str
    product_data: dict
    group: str | None = None


@dataclass
class BlockCompareEvent:
    message_id: str
    block_id: str
    payload: dict


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


class RecoverableAgentError(RuntimeError):
    """可反馈给 LLM 修正的边界错误。"""

    def __init__(
        self,
        error_type: str,
        message: str,
        *,
        raw_output: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.raw_output = raw_output
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self.details = details or {}

    @property
    def retry_key(self) -> str:
        if self.tool_name:
            return f"{self.error_type}:{self.tool_name}"
        return self.error_type

    def to_feedback(self, *, retry_count: int) -> str:
        payload = {
            "error_type": self.error_type,
            "message": self.message,
            "retry_count": retry_count,
            "max_retries": _MAX_RECOVERY_RETRIES,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "details": self.details,
            "raw_output": _truncate_for_log(self.raw_output or "", _LOG_LLM_OUTPUT_MAX_CHARS)
            if self.raw_output
            else None,
        }
        return (
            "上一轮输出无法被系统消费，请只修正导致失败的部分并重新回答。\n"
            "错误信息如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
            "要求：\n"
            "- 如果是工具调用错误，请重新生成合法的工具名和 JSON 参数。\n"
            "- 如果是推荐标记错误，请严格使用 <R><INTRO>...</INTRO>"
            '<ITEM id="商品ID"><REASON>...</REASON></ITEM></R>。\n'
            "- 如果是对比标记错误，请严格使用 "
            '<C>{"products":[...],"rows":[...]}</C>，且二者不能同时出现。\n'
            "- 推荐场景 <R> 外不要写任何非空正文；非推荐场景不要输出 <R>。\n"
            "- 不要解释修正过程。"
        )


class AgentRecoveryExhausted(RuntimeError):
    def __init__(self, error: RecoverableAgentError, retry_count: int) -> None:
        super().__init__(
            f"Agent 连续 {retry_count} 次遇到同类可恢复错误后停止："
            f"{error.error_type} - {error.message}"
        )
        self.error = error
        self.retry_count = retry_count

    def to_payload(self) -> dict:
        return {
            "error_type": self.error.error_type,
            "message": self.error.message,
            "attempts": self.retry_count,
            "tool_name": self.error.tool_name,
            "tool_call_id": self.error.tool_call_id,
            "details": self.error.details,
            "recoverable": False,
        }


@dataclass
class RecoveryState:
    retry_key: str | None = None
    retry_count: int = 0
    total_count: int = 0

    def record(self, error: RecoverableAgentError, *, label: str) -> str:
        self.total_count += 1
        if error.retry_key == self.retry_key:
            self.retry_count += 1
        else:
            self.retry_key = error.retry_key
            self.retry_count = 1

        if (
            self.retry_count > _MAX_RECOVERY_RETRIES
            or self.total_count > _MAX_TOTAL_RECOVERY_ATTEMPTS
        ):
            logger.error(
                "agent_recovery_exhausted label=%s error_type=%s retry_key=%s "
                "retry_count=%s total_count=%s details=%s raw_output=%s",
                label,
                error.error_type,
                error.retry_key,
                self.retry_count,
                self.total_count,
                _json_for_log(error.details, _LOG_ARGUMENTS_MAX_CHARS),
                _truncate_for_log(error.raw_output or "", _LOG_LLM_OUTPUT_MAX_CHARS),
            )
            raise AgentRecoveryExhausted(error, self.retry_count) from error

        logger.warning(
            "agent_recoverable_error label=%s error_type=%s retry_key=%s "
            "retry_count=%s total_count=%s message=%s details=%s raw_output=%s",
            label,
            error.error_type,
            error.retry_key,
            self.retry_count,
            self.total_count,
            error.message,
            _json_for_log(error.details, _LOG_ARGUMENTS_MAX_CHARS),
            _truncate_for_log(error.raw_output or "", _LOG_LLM_OUTPUT_MAX_CHARS),
        )
        return error.to_feedback(retry_count=self.retry_count)

    def reset(self) -> None:
        self.retry_key = None
        self.retry_count = 0
        self.total_count = 0


async def run_turn(
    conversation_id: str,
    user_message: str,
) -> AsyncIterator[
    CartEvent
    | BlockTextEvent
    | BlockTextDeltaEvent
    | BlockProductEvent
    | BlockCompareEvent
    | StructuredStatusEvent
]:
    """执行一轮对话，yield block/cart/status 事件。"""
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
            "content": SYSTEM_PROMPT,
        }
    ] + history
    candidates_by_id: dict[str, dict] = {}
    candidate_groups: list[dict] = []
    recovery = RecoveryState()
    used_retrieve_tool = False
    message_id = f"asst-{uuid4().hex}"

    step_index = 0
    while step_index < _MAX_TOOL_STEPS:
        label = f"react_step_{step_index + 1}"
        try:
            if used_retrieve_tool:
                yield StructuredStatusEvent(
                    phase="composing",
                    message="正在整理推荐...",
                    step=3,
                    total_steps=4,
                )
            response = await _create_chat_completion(
                client,
                label=label,
                model=ARK_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                temperature=0.3,
            )
            assistant_msg = _assistant_message_or_raise(response)

            if not assistant_msg.tool_calls:
                parsed_response = _parse_final_response(
                    assistant_msg.content or "",
                    require_recommend_marker=used_retrieve_tool,
                    candidate_ids=set(candidates_by_id),
                    candidate_groups=candidate_groups,
                )
                _append_final_response(
                    conversation_id,
                    parsed_response,
                    candidates_by_id,
                )
                async for event in _events_from_parsed_response(
                    parsed_response,
                    candidates_by_id,
                    message_id=message_id,
                ):
                    yield event
                return

            tool_call_msg = _tool_call_message(assistant_msg.tool_calls)
            messages.append(tool_call_msg)
            tool_history_messages = []
            tool_failed = False
            executed_finalizing_tool = False

            for tool_call in assistant_msg.tool_calls:
                try:
                    tool_name, arguments = _parse_tool_call(tool_call)
                    _log_tool_request(tool_call.id, tool_name, arguments)
                    tool_start = time.perf_counter()

                    if _is_retrieve_tool(tool_name):
                        yield StructuredStatusEvent(
                            phase="retrieving",
                            message="正在检索商品...",
                            step=1,
                            total_steps=4,
                        )
                        try:
                            current_candidate_groups = execute_tool(tool_name, arguments)
                        except Exception as exc:
                            raise _recoverable_tool_execution_error(
                                tool_call,
                                exc,
                            ) from exc
                        used_retrieve_tool = True
                        yield StructuredStatusEvent(
                            phase="filtering",
                            message="正在筛选库存和价格...",
                            step=2,
                            total_steps=4,
                        )
                        _log_tool_result(
                            tool_call.id,
                            tool_name,
                            current_candidate_groups,
                            tool_start,
                        )
                        candidate_groups.extend(current_candidate_groups)
                        candidates_by_id.update(
                            {
                                product["product_id"]: product
                                for product in _flatten_candidate_groups(
                                    current_candidate_groups
                                )
                            }
                        )
                        tool_content = _format_candidate_groups(current_candidate_groups)
                        history_content = _format_candidate_groups_compact(
                            current_candidate_groups
                        )
                    elif _is_cart_tool(tool_name):
                        executed_finalizing_tool = True
                        yield StructuredStatusEvent(
                            phase="cart",
                            message=_cart_status(tool_name),
                        )
                        try:
                            result = execute_tool(tool_name, arguments, conversation_id)
                        except Exception as exc:
                            raise _recoverable_tool_execution_error(
                                tool_call,
                                exc,
                            ) from exc
                        _log_tool_result(tool_call.id, tool_name, result, tool_start)
                        if result.get("success") and result.get("cart"):
                            yield CartEvent(result["cart"])
                        tool_content = json.dumps(result, ensure_ascii=False)
                        history_content = tool_content
                    else:
                        try:
                            result = execute_tool(tool_name, arguments)
                        except Exception as exc:
                            raise _recoverable_tool_execution_error(
                                tool_call,
                                exc,
                            ) from exc
                        _log_tool_result(tool_call.id, tool_name, result, tool_start)
                        tool_content = json.dumps(result, ensure_ascii=False)
                        history_content = tool_content
                except RecoverableAgentError as exc:
                    tool_failed = True
                    tool_content = _tool_error_content(exc)
                    feedback = recovery.record(exc, label=label)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_content,
                        }
                    )
                    _append_skipped_tool_errors(
                        messages,
                        assistant_msg.tool_calls,
                        after_tool_call_id=tool_call.id,
                    )
                    messages.append({"role": "system", "content": feedback})
                    break

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_content,
                }
                messages.append(tool_msg)
                tool_history_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": history_content,
                    }
                )

            if tool_failed:
                continue

            conversation.append(conversation_id, tool_call_msg)
            for history_message in tool_history_messages:
                conversation.append(conversation_id, history_message)
            recovery.reset()
            if used_retrieve_tool or executed_finalizing_tool:
                async for event in _stream_final_response_with_recovery(
                    client,
                    conversation_id=conversation_id,
                    messages=messages,
                    candidates_by_id=candidates_by_id,
                    candidate_groups=candidate_groups,
                    require_recommend_marker=used_retrieve_tool,
                    message_id=message_id,
                    recovery=recovery,
                    label="final_stream",
                ):
                    yield event
                return
            step_index += 1
        except RecoverableAgentError as exc:
            feedback = recovery.record(exc, label=label)
            messages.append({"role": "system", "content": feedback})
            continue

    while True:
        label = "final_after_tool_limit"
        try:
            if used_retrieve_tool:
                yield StructuredStatusEvent(
                    phase="composing",
                    message="正在整理推荐...",
                    step=3,
                    total_steps=4,
                )
            async for event in _stream_final_response(
                client,
                conversation_id=conversation_id,
                messages=messages
                + [
                    {
                        "role": "system",
                        "content": "工具调用次数已达上限，请基于已有工具结果直接回复用户；如果信息仍不足，请追问用户。",
                    }
                ],
                candidates_by_id=candidates_by_id,
                candidate_groups=candidate_groups,
                require_recommend_marker=used_retrieve_tool,
                message_id=message_id,
                label=label,
            ):
                yield event
            return
        except RecoverableAgentError as exc:
            feedback = recovery.record(exc, label=label)
            messages.append({"role": "system", "content": feedback})


async def _create_chat_completion(
    client: AsyncOpenAI,
    *,
    label: str,
    **kwargs,
):
    start = time.perf_counter()
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        logger.info(
            "llm_call_cancelled label=%s model=%s duration_ms=%.2f",
            label,
            kwargs.get("model"),
            _elapsed_ms(start),
        )
        raise
    except TimeoutError as exc:
        elapsed_ms = _elapsed_ms(start)
        logger.warning(
            "llm_call_timeout label=%s model=%s duration_ms=%.2f timeout_seconds=%s",
            label,
            kwargs.get("model"),
            elapsed_ms,
            _LLM_TIMEOUT_SECONDS,
        )
        raise RecoverableAgentError(
            "llm_timeout",
            f"LLM 调用超过 {_LLM_TIMEOUT_SECONDS} 秒无响应。",
            details={
                "label": label,
                "model": kwargs.get("model"),
                "timeout_seconds": _LLM_TIMEOUT_SECONDS,
                "duration_ms": elapsed_ms,
            },
        ) from exc
    except Exception as exc:
        elapsed_ms = _elapsed_ms(start)
        logger.exception(
            "llm_call_error label=%s model=%s duration_ms=%.2f",
            label,
            kwargs.get("model"),
            elapsed_ms,
        )
        raise RecoverableAgentError(
            "llm_call_error",
            f"LLM 调用失败：{exc}",
            details={
                "label": label,
                "model": kwargs.get("model"),
                "duration_ms": elapsed_ms,
                "exception_type": type(exc).__name__,
            },
        ) from exc
    elapsed_ms = _elapsed_ms(start)
    finish_reason = response.choices[0].finish_reason if response.choices else None
    logger.info(
        "llm_call label=%s model=%s duration_ms=%.2f finish_reason=%s",
        label,
        kwargs.get("model"),
        elapsed_ms,
        finish_reason,
    )
    return response


async def _stream_final_response_with_recovery(
    client: AsyncOpenAI,
    *,
    conversation_id: str,
    messages: list[dict],
    candidates_by_id: dict[str, dict],
    candidate_groups: list[dict],
    require_recommend_marker: bool,
    message_id: str,
    recovery: RecoveryState,
    label: str,
) -> AsyncIterator[
    BlockTextEvent
    | BlockTextDeltaEvent
    | BlockProductEvent
    | BlockCompareEvent
    | StructuredStatusEvent
]:
    while True:
        try:
            async for event in _stream_final_response(
                client,
                conversation_id=conversation_id,
                messages=messages,
                candidates_by_id=candidates_by_id,
                candidate_groups=candidate_groups,
                require_recommend_marker=require_recommend_marker,
                message_id=message_id,
                label=label,
            ):
                yield event
            return
        except RecoverableAgentError as exc:
            feedback = recovery.record(exc, label=label)
            messages.append({"role": "system", "content": feedback})


async def _stream_final_response(
    client: AsyncOpenAI,
    *,
    conversation_id: str,
    messages: list[dict],
    candidates_by_id: dict[str, dict],
    candidate_groups: list[dict],
    require_recommend_marker: bool,
    message_id: str,
    label: str,
) -> AsyncIterator[
    BlockTextEvent
    | BlockTextDeltaEvent
    | BlockProductEvent
    | BlockCompareEvent
    | StructuredStatusEvent
]:
    yield StructuredStatusEvent(
        phase="streaming",
        message="正在输出推荐..." if require_recommend_marker else "正在输出回复...",
        step=4 if require_recommend_marker else None,
        total_steps=4 if require_recommend_marker else None,
    )
    emitter = _StreamingFinalEmitter(
        message_id=message_id,
        candidates_by_id=candidates_by_id,
        candidate_groups=candidate_groups,
        require_recommend_marker=require_recommend_marker,
    )
    start = time.perf_counter()
    first_chunk_ms: float | None = None
    completed = False
    chunk_count = 0
    stream = None
    try:
        stream = await asyncio.wait_for(
            client.chat.completions.create(
                model=ARK_MODEL,
                messages=messages,
                temperature=0.3,
                stream=True,
            ),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
        async for chunk in stream:
            chunk_count += 1
            if first_chunk_ms is None:
                first_chunk_ms = _elapsed_ms(start)
            delta = chunk.choices[0].delta if chunk.choices else None
            text_delta = getattr(delta, "content", None) if delta is not None else None
            if not text_delta:
                continue
            for event in emitter.feed(text_delta):
                yield event
        parsed_response = emitter.finish()
        if parsed_response.compare_payload:
            async for event in _events_from_parsed_response(
                parsed_response,
                candidates_by_id,
                message_id=message_id,
            ):
                yield event
        _append_final_response(conversation_id, parsed_response, candidates_by_id)
        completed = True
        logger.info(
            "llm_stream_call label=%s model=%s duration_ms=%.2f first_chunk_ms=%s "
            "first_visible_ms=%s chunks=%s visible_chars=%s",
            label,
            ARK_MODEL,
            _elapsed_ms(start),
            f"{first_chunk_ms:.2f}" if first_chunk_ms is not None else None,
            (
                f"{emitter.first_visible_ms:.2f}"
                if emitter.first_visible_ms is not None
                else None
            ),
            chunk_count,
            emitter.visible_char_count,
        )
    except asyncio.CancelledError:
        logger.info(
            "llm_call_cancelled label=%s model=%s duration_ms=%.2f chunks=%s",
            label,
            ARK_MODEL,
            _elapsed_ms(start),
            chunk_count,
        )
        raise
    except TimeoutError as exc:
        raise RecoverableAgentError(
            "llm_timeout",
            f"LLM streaming 调用超过 {_LLM_TIMEOUT_SECONDS} 秒无响应。",
            details={
                "label": label,
                "model": ARK_MODEL,
                "timeout_seconds": _LLM_TIMEOUT_SECONDS,
                "duration_ms": _elapsed_ms(start),
            },
        ) from exc
    except RecoverableAgentError:
        raise
    except Exception as exc:
        logger.exception(
            "llm_stream_call_error label=%s model=%s duration_ms=%.2f",
            label,
            ARK_MODEL,
            _elapsed_ms(start),
        )
        raise RecoverableAgentError(
            "llm_call_error",
            f"LLM streaming 调用失败：{exc}",
            details={
                "label": label,
                "model": ARK_MODEL,
                "duration_ms": _elapsed_ms(start),
                "exception_type": type(exc).__name__,
            },
        ) from exc
    finally:
        if not completed and emitter.has_visible_output:
            conversation.append(
                conversation_id,
                {
                    "role": "assistant",
                    "content": emitter.interrupted_history_text(candidates_by_id),
                },
            )
        if stream is not None and hasattr(stream, "aclose"):
            with contextlib.suppress(Exception):
                await stream.aclose()


class _StreamingFinalEmitter:
    def __init__(
        self,
        *,
        message_id: str,
        candidates_by_id: dict[str, dict],
        candidate_groups: list[dict],
        require_recommend_marker: bool,
    ) -> None:
        self.message_id = message_id
        self.candidates_by_id = candidates_by_id
        self.candidate_ids = set(candidates_by_id)
        self.candidate_groups = candidate_groups
        self.require_recommend_marker = require_recommend_marker
        self.buffer = ""
        self.raw_output = ""
        self.mode: str | None = None
        self.state = "start"
        self.block_index = 1
        self.current_block_id: str | None = None
        self.current_item: RecommendationItem | None = None
        self.intro = ""
        self.outro: str | None = None
        self.items: list[RecommendationItem] = []
        self.normal_block_id: str | None = None
        self.started_at = time.perf_counter()
        self.first_visible_ms: float | None = None
        self.visible_char_count = 0
        self.visible_text_parts: list[str] = []
        self.visible_products: list[str] = []

    @property
    def has_visible_output(self) -> bool:
        return bool(self.visible_text_parts or self.visible_products)

    def feed(
        self,
        chunk: str,
    ) -> list[BlockTextDeltaEvent | BlockProductEvent | BlockCompareEvent]:
        self.raw_output += chunk
        self.buffer += chunk
        if self.mode is None:
            return self._detect_mode()
        if self.mode == "recommend":
            return self._drain_recommendation()
        if self.mode == "text":
            return self._emit_normal_text(self.buffer)
        if self.mode == "compare":
            return []
        return []

    def finish(self) -> ParsedFinalResponse:
        if self.mode in {"text", "compare"}:
            parsed_response = _parse_final_response(
                self.raw_output,
                require_recommend_marker=self.require_recommend_marker,
                candidate_ids=self.candidate_ids,
                candidate_groups=self.candidate_groups,
            )
            return parsed_response
        if self.mode == "recommend" and self.state != "done":
            raise RecoverableAgentError(
                "hidden_marker_invalid",
                "<R> 推荐标记未正确闭合。",
                raw_output=self.raw_output,
                details={"state": self.state, "buffer": self.buffer},
            )
        parsed_response = _parse_final_response(
            self.raw_output,
            require_recommend_marker=self.require_recommend_marker,
            candidate_ids=self.candidate_ids,
            candidate_groups=self.candidate_groups,
        )
        return parsed_response

    def interrupted_history_text(self, candidates_by_id: dict[str, dict]) -> str:
        if self.items:
            recommendation = ParsedRecommendation(
                intro=self.intro,
                items=self.items,
                outro=self.outro,
            )
            text = _recommendation_history_text(recommendation, candidates_by_id)
        else:
            text = "".join(self.visible_text_parts).strip()
            for product_id in self.visible_products:
                product = candidates_by_id.get(product_id, {})
                title = product.get("title") or product_id
                text += f"\n[商品] {title}（product_id={product_id}）"
        return f"{text.strip()}\n[interrupted]".strip()

    def _detect_mode(
        self,
    ) -> list[BlockTextDeltaEvent | BlockProductEvent | BlockCompareEvent]:
        stripped = self.buffer.lstrip()
        if not stripped:
            self.buffer = stripped
            return []
        if stripped in {"<", "<R", "<C"}:
            self.buffer = stripped
            return []
        if stripped.startswith("<R"):
            if ">" not in stripped:
                self.buffer = stripped
                return []
            tag = stripped[: stripped.index(">") + 1]
            if tag != "<R>":
                raise RecoverableAgentError(
                    "hidden_marker_invalid",
                    "推荐块必须以 <R> 开始且 <R> 不允许包含属性。",
                    raw_output=self.raw_output,
                    details={"tag": tag},
                )
            self.mode = "recommend"
            self.state = "await_child"
            self.buffer = stripped[len(tag) :]
            return self._drain_recommendation()
        if stripped.startswith("<C"):
            self.mode = "compare"
            self.buffer = stripped
            return []
        if self.require_recommend_marker:
            raise RecoverableAgentError(
                "recommend_marker_missing",
                "本轮调用过 retrieve_products，最终回复必须输出 <R>...</R> 推荐块。",
                raw_output=self.raw_output,
                details={"candidate_ids": sorted(self.candidate_ids)},
            )
        self.mode = "text"
        return self._emit_normal_text(self.buffer)

    def _drain_recommendation(
        self,
    ) -> list[BlockTextDeltaEvent | BlockProductEvent]:
        events: list[BlockTextDeltaEvent | BlockProductEvent] = []
        while self.buffer:
            if self.state in {"await_child", "inside_item"}:
                stripped = self.buffer.lstrip()
                if not stripped:
                    self.buffer = stripped
                    break
                if not stripped.startswith("<"):
                    raise RecoverableAgentError(
                        "recommend_marker_invalid",
                        "推荐标签内不允许出现未包裹的正文。",
                        raw_output=self.raw_output,
                        details={"state": self.state, "text": stripped[:30]},
                    )
                if ">" not in stripped:
                    self.buffer = stripped
                    break
                tag = stripped[: stripped.index(">") + 1]
                self.buffer = stripped[len(tag) :]
                events.extend(self._handle_recommendation_tag(tag))
                continue

            if self.state in {"intro_text", "reason_text", "outro_text"}:
                tag_index = self.buffer.find("<")
                if tag_index == -1:
                    text = self.buffer
                    self.buffer = ""
                    events.extend(self._emit_recommendation_text(text))
                    break
                if tag_index == 0:
                    if ">" not in self.buffer:
                        break
                    tag = self.buffer[: self.buffer.index(">") + 1]
                    self.buffer = self.buffer[len(tag) :]
                    events.extend(self._handle_recommendation_tag(tag))
                    continue
                text = self.buffer[:tag_index]
                self.buffer = self.buffer[tag_index:]
                events.extend(self._emit_recommendation_text(text))
                continue

            if self.state == "done":
                if self.buffer.strip():
                    raise RecoverableAgentError(
                        "recommend_marker_visible_text_outside",
                        "推荐场景中 <R>...</R> 外不允许有非空正文。",
                        raw_output=self.raw_output,
                        details={"outside_text": self.buffer.strip()},
                    )
                self.buffer = ""
                break
        return events

    def _handle_recommendation_tag(
        self,
        tag: str,
    ) -> list[BlockProductEvent]:
        if tag == "<INTRO>" and self.state == "await_child" and not self.intro and not self.items:
            self.current_block_id = self._next_block_id()
            self.state = "intro_text"
            return []
        if tag == "</INTRO>" and self.state == "intro_text":
            self.state = "await_child"
            return []
        if tag.startswith("<ITEM ") and self.state == "await_child":
            item = self._parse_streaming_item_tag(tag)
            product = self.candidates_by_id[item.product_id]
            self.current_item = item
            self.visible_products.append(item.product_id)
            self.state = "inside_item"
            return [
                BlockProductEvent(
                    message_id=self.message_id,
                    block_id=self._next_block_id(),
                    product_id=item.product_id,
                    product_data=product,
                    group=item.group,
                )
            ]
        if tag == "<REASON>" and self.state == "inside_item" and self.current_item:
            self.current_block_id = self._next_block_id()
            self.state = "reason_text"
            return []
        if tag == "</REASON>" and self.state == "reason_text" and self.current_item:
            self.items.append(self.current_item)
            self.current_item = None
            self.state = "inside_item"
            return []
        if tag == "</ITEM>" and self.state == "inside_item" and self.current_item is None:
            self.state = "await_child"
            return []
        if tag == "<OUTRO>" and self.state == "await_child" and self.items:
            self.current_block_id = self._next_block_id()
            self.state = "outro_text"
            return []
        if tag == "</OUTRO>" and self.state == "outro_text":
            self.state = "await_child"
            return []
        if tag == "</R>" and self.state == "await_child":
            self.state = "done"
            return []
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "推荐标记顺序或嵌套不合法。",
            raw_output=self.raw_output,
            details={"tag": tag, "state": self.state},
        )

    def _parse_streaming_item_tag(self, tag: str) -> RecommendationItem:
        match = re.fullmatch(
            r'<ITEM\s+id="([^"<>\\]*)"(?:\s+group="([^"<>\\]*)")?\s*>',
            tag,
        )
        if not match:
            raise RecoverableAgentError(
                "recommend_marker_invalid_attr",
                "<ITEM> 开始标签只允许 id 和可选 group 属性。",
                raw_output=self.raw_output,
                details={"tag": tag},
            )
        product_id = match.group(1).strip()
        group = (match.group(2) or "").strip() or None
        _validate_item_attr_value(product_id, raw_output=self.raw_output, attr_name="id")
        if group:
            _validate_item_attr_value(group, raw_output=self.raw_output, attr_name="group")
        self._validate_streaming_item_group(product_id, group)
        return RecommendationItem(product_id=product_id, reason="", group=group)

    def _validate_streaming_item_group(
        self,
        product_id: str,
        group: str | None,
    ) -> None:
        if product_id not in self.candidate_ids:
            raise RecoverableAgentError(
                "recommend_marker_unknown_ids",
                "<ITEM> 中包含本轮工具结果里不存在的商品 ID。",
                raw_output=self.raw_output,
                details={
                    "unknown_ids": [product_id],
                    "candidate_ids": sorted(self.candidate_ids),
                },
            )
        group_product_ids = _candidate_group_product_ids(self.candidate_groups)
        require_group = len(group_product_ids) > 1
        if require_group:
            if not group or group not in group_product_ids:
                raise RecoverableAgentError(
                    "recommend_marker_invalid_group",
                    "<ITEM> group 必须来自本轮 retrieve_products 的 request label。",
                    raw_output=self.raw_output,
                    details={"group": group, "valid_groups": sorted(group_product_ids)},
                )
            if product_id not in group_product_ids[group]:
                raise RecoverableAgentError(
                    "recommend_marker_invalid_group",
                    "<ITEM> id 必须属于对应 group 的候选商品。",
                    raw_output=self.raw_output,
                    details={"group": group, "product_id": product_id},
                )
        elif group:
            raise RecoverableAgentError(
                "recommend_marker_invalid_group",
                "单 request 或无 label 推荐场景中 <ITEM> 不允许包含 group。",
                raw_output=self.raw_output,
                details={"group": group},
            )

    def _emit_recommendation_text(self, text: str) -> list[BlockTextDeltaEvent]:
        if not text:
            return []
        if self.state == "intro_text":
            self.intro += text
        elif self.state == "reason_text" and self.current_item:
            self.current_item.reason += text
        elif self.state == "outro_text":
            self.outro = (self.outro or "") + text
        return self._emit_text_delta(text, self.current_block_id)

    def _emit_normal_text(self, text: str) -> list[BlockTextDeltaEvent]:
        self.buffer = ""
        if self.normal_block_id is None:
            self.normal_block_id = self._next_block_id()
        return self._emit_text_delta(text, self.normal_block_id)

    def _emit_text_delta(
        self,
        text: str,
        block_id: str | None,
    ) -> list[BlockTextDeltaEvent]:
        if not text or block_id is None:
            return []
        self._record_first_visible()
        self.visible_char_count += len(text)
        self.visible_text_parts.append(text)
        return [
            BlockTextDeltaEvent(
                message_id=self.message_id,
                block_id=block_id,
                content=part,
            )
            for part in _split_text_delta(text)
        ]

    def _next_block_id(self) -> str:
        block_id = f"blk-{self.block_index}"
        self.block_index += 1
        return block_id

    def _record_first_visible(self) -> None:
        if self.first_visible_ms is None:
            self.first_visible_ms = _elapsed_ms(self.started_at)


def _split_text_delta(text: str) -> list[str]:
    parts: list[str] = []
    index = 0
    while index < len(text):
        step = 1 if _is_cjk(text[index]) else 3
        parts.append(text[index : index + step])
        index += step
    return parts


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _assistant_message_or_raise(response):
    if not response.choices:
        raise RecoverableAgentError(
            "llm_empty_response",
            "LLM 响应中没有 choices。",
            details={"response": str(response)},
        )
    message = response.choices[0].message
    if message is None:
        raise RecoverableAgentError(
            "llm_empty_response",
            "LLM 响应中没有 assistant message。",
            details={"finish_reason": response.choices[0].finish_reason},
        )
    return message


def _parse_tool_call(tool_call) -> tuple[str, dict]:
    tool_name = tool_call.function.name
    raw_arguments = tool_call.function.arguments or "{}"
    try:
        arguments = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RecoverableAgentError(
            "tool_arguments_invalid",
            f"工具 {tool_name} 的参数不是合法 JSON：{exc}",
            raw_output=raw_arguments,
            tool_name=tool_name,
            tool_call_id=tool_call.id,
            details={"exception_type": type(exc).__name__},
        ) from exc
    if not isinstance(arguments, dict):
        raise RecoverableAgentError(
            "tool_arguments_invalid",
            f"工具 {tool_name} 的参数必须是 JSON object。",
            raw_output=raw_arguments,
            tool_name=tool_name,
            tool_call_id=tool_call.id,
            details={"actual_type": type(arguments).__name__},
        )
    return tool_name, arguments


def _log_tool_request(tool_call_id: str, tool_name: str, arguments: dict) -> None:
    logger.info(
        "tool_call_request id=%s name=%s arguments=%s",
        tool_call_id,
        tool_name,
        _json_for_log(arguments, _LOG_ARGUMENTS_MAX_CHARS),
    )


def _log_tool_result(
    tool_call_id: str,
    tool_name: str,
    result,
    started_at: float,
) -> None:
    logger.info(
        "tool_call_result id=%s name=%s duration_ms=%.2f result=%s",
        tool_call_id,
        tool_name,
        _elapsed_ms(started_at),
        _json_for_log(result, _LOG_TOOL_RESULT_MAX_CHARS),
    )


def _elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000


def _json_for_log(value, max_chars: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return _truncate_for_log(text, max_chars)


def _truncate_for_log(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...<truncated {len(text) - max_chars} chars>"


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
    parsed_response: ParsedFinalResponse,
    candidates_by_id: dict[str, dict],
) -> None:
    clean_text = parsed_response.history_text or parsed_response.clean_text
    if parsed_response.recommendation:
        clean_text = _recommendation_history_text(
            parsed_response.recommendation,
            candidates_by_id,
        )
    conversation.append(
        conversation_id,
        {"role": "assistant", "content": clean_text.strip()},
    )


async def _events_from_parsed_response(
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


def _parse_recommendation_marker(
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
    _ensure_whitespace_only(root.text, raw_output=raw_output, location="R.text")

    group_product_ids = _candidate_group_product_ids(candidate_groups)
    group_labels = set(group_product_ids)
    require_group = len(group_labels) > 1
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
        _ensure_whitespace_only(child.tail, raw_output=raw_output, location=f"{child.tag}.tail")

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
            _validate_mobile_visible_reply(
                intro,
                raw_output=raw_output,
                enforce_length=True,
                max_chars=_RECOMMEND_FIELD_LIMITS["INTRO"],
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
            item = _parse_recommendation_item(
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
                _validate_mobile_visible_reply(
                    outro_text,
                    raw_output=raw_output,
                    enforce_length=True,
                    max_chars=_RECOMMEND_FIELD_LIMITS["OUTRO"],
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


def _parse_recommendation_item(
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
    _validate_item_attr_value(product_id, raw_output=raw_output, attr_name="id")
    if group is not None:
        _validate_item_attr_value(group, raw_output=raw_output, attr_name="group")
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

    _ensure_whitespace_only(item_el.text, raw_output=raw_output, location="ITEM.text")
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
    _ensure_whitespace_only(
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
    _validate_mobile_visible_reply(
        reason,
        raw_output=raw_output,
        enforce_length=True,
        max_chars=_RECOMMEND_FIELD_LIMITS["REASON"],
        field_name="REASON",
    )
    return RecommendationItem(product_id=product_id, reason=reason, group=group)


def _validate_item_attr_value(value: str, *, raw_output: str, attr_name: str) -> None:
    if not value or not _ITEM_ATTR_VALUE_RE.fullmatch(value):
        raise RecoverableAgentError(
            "recommend_marker_invalid_attr",
            "<ITEM> 属性值只能包含字母、数字、汉字、-、_、空格、冒号和斜杠。",
            raw_output=raw_output,
            details={"attr_name": attr_name, "value": value},
        )


def _ensure_whitespace_only(
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


def _candidate_group_product_ids(candidate_groups: list[dict]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for group in candidate_groups:
        label = (group.get("label") or "").strip()
        if not label:
            continue
        grouped.setdefault(label, set()).update(
            product["product_id"]
            for product in group.get("products", [])
            if product.get("product_id")
        )
    return grouped


def _parse_final_response(
    text: str,
    *,
    require_recommend_marker: bool,
    candidate_ids: set[str],
    candidate_groups: list[dict] | None = None,
) -> ParsedFinalResponse:
    _validate_marker_syntax(text)
    recommend_matches = list(re.finditer(r"<R\b[^>]*>.*?</R>\s*", text, flags=re.DOTALL))
    compare_matches = list(re.finditer(r"<C>(.*?)</C>\n?", text, flags=re.DOTALL))

    if len(recommend_matches) > 1:
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            "回复中只能出现一个 <R> 推荐标记。",
            raw_output=text,
            details={"recommend_marker_count": len(recommend_matches)},
        )
    if len(compare_matches) > 1:
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            "回复中只能出现一个 <C> 对比标记。",
            raw_output=text,
            details={"compare_marker_count": len(compare_matches)},
        )
    if recommend_matches and compare_matches:
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            "<R> 和 <C> 不能同时出现在同一条回复中。",
            raw_output=text,
        )
    if require_recommend_marker and not recommend_matches:
        raise RecoverableAgentError(
            "recommend_marker_missing",
            "本轮调用过 retrieve_products，最终回复必须输出 <R>...</R> 推荐块。",
            raw_output=text,
            details={"candidate_ids": sorted(candidate_ids)},
        )

    if recommend_matches:
        recommend_match = recommend_matches[0]
        outside_text = text[: recommend_match.start()] + text[recommend_match.end() :]
        if outside_text.strip():
            raise RecoverableAgentError(
                "recommend_marker_visible_text_outside",
                "推荐场景中 <R>...</R> 外不允许有非空正文。",
                raw_output=text,
                details={"outside_text": outside_text.strip()},
            )
        recommendation = _parse_recommendation_marker(
            recommend_match.group(0).strip(),
            raw_output=text,
            candidate_ids=candidate_ids,
            candidate_groups=candidate_groups or [],
        )
        if require_recommend_marker and candidate_ids and not recommendation.items:
            raise RecoverableAgentError(
                "recommend_marker_empty",
                "本轮工具返回了候选商品，<R> 中至少需要包含 1 个推荐商品。",
                raw_output=text,
                details={"candidate_ids": sorted(candidate_ids)},
            )
        clean_text = _recommendation_visible_text(recommendation)
        return ParsedFinalResponse(recommendation, None, clean_text)

    clean_text = _strip_hidden_event_marker_text(text)
    if not clean_text.strip():
        raise RecoverableAgentError(
            "visible_reply_empty",
            "去除隐藏事件标记后，用户可见回复为空。",
            raw_output=text,
        )

    if compare_matches:
        compare_match = compare_matches[0]
        _ensure_marker_is_first_line(text, compare_match, "<C>")
        compare_payload = _loads_compare_payload_or_raise(
            compare_match.group(1),
            raw_output=text,
        )
        _validate_mobile_visible_reply(
            clean_text,
            raw_output=text,
            enforce_length=True,
        )
        return ParsedFinalResponse(None, compare_payload, clean_text)

    _validate_mobile_visible_reply(
        text,
        raw_output=text,
        enforce_length=False,
    )
    return ParsedFinalResponse(None, None, text)


def _validate_marker_syntax(text: str) -> None:
    invalid_tokens = [
        token
        for token in _MARKER_TAG_RE.findall(text)
        if token not in {"<R>", "</R>", "<C>", "</C>"}
    ]
    if invalid_tokens:
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            "回复中包含非法隐藏事件标记。",
            raw_output=text,
            details={"invalid_tokens": invalid_tokens},
        )
    for marker in ("R", "C"):
        open_count = text.count(f"<{marker}>")
        close_count = text.count(f"</{marker}>")
        if open_count != close_count:
            raise RecoverableAgentError(
                "hidden_marker_invalid",
                f"<{marker}> 标记未正确闭合。",
                raw_output=text,
                details={
                    "marker": marker,
                    "open_count": open_count,
                    "close_count": close_count,
                },
            )


def _ensure_marker_is_first_line(text: str, match: re.Match, marker_name: str) -> None:
    if text[: match.start()].strip():
        raise RecoverableAgentError(
            "hidden_marker_invalid",
            f"{marker_name} 标记必须位于最终回复第一行开头。",
            raw_output=text,
            details={"marker": marker_name},
        )


def _validate_mobile_visible_reply(
    visible_text: str,
    *,
    raw_output: str,
    enforce_length: bool,
    max_chars: int = _MOBILE_VISIBLE_REPLY_MAX_CHARS,
    field_name: str = "visible_reply",
) -> None:
    stripped_text = visible_text.strip()
    markdown_match = _VISIBLE_MARKDOWN_TOKEN_RE.search(stripped_text)
    if markdown_match:
        raise RecoverableAgentError(
            "visible_reply_markdown",
            "用户可见回复不能包含 Markdown 标题、加粗、表格或分隔线语法。",
            raw_output=raw_output,
            details={"token": markdown_match.group(0)},
        )
    if enforce_length and len(stripped_text) > max_chars:
        raise RecoverableAgentError(
            "visible_reply_too_long",
            f"{field_name} 不能超过 {max_chars} 个字符。",
            raw_output=raw_output,
            details={
                "field_name": field_name,
                "max_chars": max_chars,
                "actual_chars": len(stripped_text),
            },
        )


def _recommendation_visible_text(recommendation: ParsedRecommendation) -> str:
    parts = [recommendation.intro]
    parts.extend(item.reason for item in recommendation.items)
    if recommendation.outro:
        parts.append(recommendation.outro)
    return "\n".join(part for part in parts if part.strip())


def _recommendation_history_text(
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


def _strip_hidden_event_marker_text(text: str) -> str:
    text = re.sub(r"<R\b[^>]*>.*?</R>\n?", "", text, flags=re.DOTALL)
    return re.sub(r"<C>.*?</C>\n?", "", text, flags=re.DOTALL)


def _loads_compare_payload_or_raise(raw_json: str, *, raw_output: str) -> dict:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RecoverableAgentError(
            "compare_marker_invalid_json",
            f"<C> 标记内容不是合法 JSON：{exc}",
            raw_output=raw_output,
            details={"exception_type": type(exc).__name__},
        ) from exc
    if not isinstance(payload, dict):
        raise RecoverableAgentError(
            "compare_marker_invalid_json",
            "<C> 标记内容必须是 JSON object。",
            raw_output=raw_output,
            details={"actual_type": type(payload).__name__},
        )
    if not isinstance(payload.get("products"), list) or not isinstance(
        payload.get("rows"),
        list,
    ):
        raise RecoverableAgentError(
            "compare_marker_invalid_schema",
            '<C> 标记 JSON 必须包含 products[] 和 rows[]。',
            raw_output=raw_output,
            details={"keys": sorted(payload)},
        )
    return payload


def _tool_error_content(error: RecoverableAgentError) -> str:
    return json.dumps(
        {
            "success": False,
            "error_type": error.error_type,
            "message": error.message,
            "tool_name": error.tool_name,
            "details": error.details,
        },
        ensure_ascii=False,
    )


def _append_skipped_tool_errors(
    messages: list[dict],
    tool_calls,
    *,
    after_tool_call_id: str,
) -> None:
    should_skip = False
    for tool_call in tool_calls:
        if tool_call.id == after_tool_call_id:
            should_skip = True
            continue
        if not should_skip:
            continue
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(
                    {
                        "success": False,
                        "error_type": "tool_call_skipped",
                        "message": "前一个工具调用失败，本工具调用未执行。请重新生成整组工具调用。",
                        "tool_name": tool_call.function.name,
                    },
                    ensure_ascii=False,
                ),
            }
        )


def _recoverable_tool_execution_error(tool_call, exc: Exception) -> RecoverableAgentError:
    return RecoverableAgentError(
        "tool_execution_error",
        f"工具 {tool_call.function.name} 执行失败：{exc}",
        raw_output=tool_call.function.arguments or "",
        tool_name=tool_call.function.name,
        tool_call_id=tool_call.id,
        details={
            "exception_type": type(exc).__name__,
            "traceback": "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
        },
    )
