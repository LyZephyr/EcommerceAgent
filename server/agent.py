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
from collections.abc import AsyncIterator
from dataclasses import dataclass

from openai import AsyncOpenAI

import conversation
from config import ARK_API_KEY, ARK_BASE_URL, ARK_MODEL
from tools import TOOL_DEFINITIONS, execute as execute_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
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
- 离线评估等只包含单条明确商品 query 的场景，直接调用 retrieve_products，且 requests 中只填写 1 个 request
- 寒暄或与购物无关的问题，直接简短回复

## 回复规则
- 只基于工具返回的商品资料回答，不编造不存在的商品、价格、功效、优惠或库存
- 价格、库存、上下架和优惠只能引用工具返回字段；没有字段时不要自行推断
- 不编造购物车中不存在的商品、价格、优惠、库存或配送承诺
- 推荐时说明理由、适合人群和需要注意的评价反馈
- 对比多个商品时，按照用户关心的维度进行对比，如果用户没有说明从哪些方面进行对比，则默认按价格、核心卖点、适合人群、评价反馈和注意事项等维度整合，不直接堆叠原始资料
- 回答自然简洁

## 隐藏事件标记
- 当最终回复是商品推荐、搜索结果、筛选结果或场景化组合推荐时，必须以一行推荐标记开头：<R>商品ID1,商品ID2</R>
- <R> 只包含你真正推荐的商品 ID。没有合适商品时输出 <R></R>
- 只要商品资料中存在可用候选，就必须至少推荐 1 个商品；场景化组合推荐优先覆盖不同子需求
- 自然语言正文中点名推荐、列入组合方案、对比差异或邀请用户加购的每个商品，其 product_id 都必须出现在 <R> 中；只有 <R> 内的 ID 才会展示商品卡片，用户也才能将其加入购物车。禁止正文推荐了某款商品却不写入 <R>
- 当用户要求基于当前会话之前已经推荐或展示过的多个商品做对比，且本轮不是新的商品推荐时，必须以一行结构化对比标记开头：
<C>{"products":[{"product_id":"商品ID","title":"商品名"}],"rows":[{"dimension":"价格","values":{"商品ID":"对比值"}}]}</C>
- <R> 和 <C> 不能同时出现在同一条回复中：基于之前推荐过的商品进行对比时只输出 <C>；商品推荐、搜索、筛选或组合推荐时只输出 <R>
- 反问澄清、寒暄、购物车操作回复和普通说明不要输出 <R> 或 <C>
- 标记后换行，必须写给用户看的自然语言回复；用户看不到这些标记"""

_MAX_TOOL_STEPS = 3
_MAX_RECOVERY_RETRIES = 2
_MAX_TOTAL_RECOVERY_ATTEMPTS = 6
_LLM_TIMEOUT_SECONDS = 60
_LOG_ARGUMENTS_MAX_CHARS = 4000
_LOG_TOOL_RESULT_MAX_CHARS = 100
_LOG_LLM_OUTPUT_MAX_CHARS = 4000
_MARKER_TAG_RE = re.compile(r"</?[RC][^>]*>")


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


@dataclass
class ParsedFinalResponse:
    recommended_ids: list[str]
    compare_payload: dict | None
    clean_text: str


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
            "- 如果是隐藏事件标记错误，请严格使用 <R>商品ID1,商品ID2</R> 或 "
            '<C>{"products":[...],"rows":[...]}</C>，且二者不能同时出现。\n'
            "- 标记后必须给出用户可见的自然语言回复。\n"
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
            "content": SYSTEM_PROMPT,
        }
    ] + history
    candidates_by_id: dict[str, dict] = {}
    recovery = RecoveryState()
    used_retrieve_tool = False

    step_index = 0
    while step_index < _MAX_TOOL_STEPS:
        label = f"react_step_{step_index + 1}"
        try:
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
                )
                _append_final_response(conversation_id, parsed_response)
                async for event in _events_from_parsed_response(
                    parsed_response,
                    candidates_by_id,
                ):
                    yield event
                return

            tool_call_msg = _tool_call_message(assistant_msg.tool_calls)
            messages.append(tool_call_msg)
            tool_history_messages = []
            tool_failed = False

            for tool_call in assistant_msg.tool_calls:
                try:
                    tool_name, arguments = _parse_tool_call(tool_call)
                    _log_tool_request(tool_call.id, tool_name, arguments)
                    tool_start = time.perf_counter()

                    if _is_retrieve_tool(tool_name):
                        yield StatusEvent("正在检索商品...")
                        try:
                            candidate_groups = execute_tool(tool_name, arguments)
                        except Exception as exc:
                            raise _recoverable_tool_execution_error(
                                tool_call,
                                exc,
                            ) from exc
                        used_retrieve_tool = True
                        _log_tool_result(
                            tool_call.id,
                            tool_name,
                            candidate_groups,
                            tool_start,
                        )
                        candidates_by_id.update(
                            {
                                product["product_id"]: product
                                for product in _flatten_candidate_groups(candidate_groups)
                            }
                        )
                        tool_content = _format_candidate_groups(candidate_groups)
                        history_content = _format_candidate_groups_compact(
                            candidate_groups
                        )
                    elif _is_cart_tool(tool_name):
                        yield StatusEvent(_cart_status(tool_name))
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
            step_index += 1
        except RecoverableAgentError as exc:
            feedback = recovery.record(exc, label=label)
            messages.append({"role": "system", "content": feedback})
            continue

    while True:
        label = "final_after_tool_limit"
        try:
            response = await _create_chat_completion(
                client,
                label=label,
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
            content = _assistant_message_or_raise(response).content or ""
            parsed_response = _parse_final_response(
                content,
                require_recommend_marker=used_retrieve_tool,
                candidate_ids=set(candidates_by_id),
            )
            _append_final_response(conversation_id, parsed_response)
            async for event in _events_from_parsed_response(
                parsed_response,
                candidates_by_id,
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


def _append_final_response(conversation_id: str, parsed_response: ParsedFinalResponse) -> None:
    clean_text = parsed_response.clean_text
    conversation.append(
        conversation_id,
        {"role": "assistant", "content": clean_text.strip()},
    )


async def _events_from_parsed_response(
    parsed_response: ParsedFinalResponse,
    candidates_by_id: dict[str, dict],
) -> AsyncIterator[ProductEvent | CompareEvent | TokenEvent]:
    for pid in parsed_response.recommended_ids:
        if pid in candidates_by_id:
            yield ProductEvent(pid, candidates_by_id[pid])
    if parsed_response.compare_payload:
        yield CompareEvent(parsed_response.compare_payload)
    if parsed_response.clean_text.strip():
        yield TokenEvent(parsed_response.clean_text)


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


def _parse_final_response(
    text: str,
    *,
    require_recommend_marker: bool,
    candidate_ids: set[str],
) -> ParsedFinalResponse:
    _validate_marker_syntax(text)
    recommend_matches = list(re.finditer(r"<R>(.*?)</R>\n?", text, flags=re.DOTALL))
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
            "本轮调用过 retrieve_products，最终回复必须以 <R>...</R> 推荐标记开头。",
            raw_output=text,
            details={"candidate_ids": sorted(candidate_ids)},
        )

    clean_text = _strip_hidden_event_marker_text(text)
    if not clean_text.strip():
        raise RecoverableAgentError(
            "visible_reply_empty",
            "去除隐藏事件标记后，用户可见回复为空。",
            raw_output=text,
        )

    if recommend_matches:
        recommend_match = recommend_matches[0]
        _ensure_marker_is_first_line(text, recommend_match, "<R>")
        recommended_ids = _parse_recommend_ids(recommend_match.group(1))
        unknown_ids = sorted(pid for pid in recommended_ids if pid not in candidate_ids)
        if unknown_ids:
            raise RecoverableAgentError(
                "recommend_marker_unknown_ids",
                "<R> 中包含本轮工具结果里不存在的商品 ID。",
                raw_output=text,
                details={
                    "unknown_ids": unknown_ids,
                    "candidate_ids": sorted(candidate_ids),
                },
            )
        if require_recommend_marker and candidate_ids and not recommended_ids:
            raise RecoverableAgentError(
                "recommend_marker_empty",
                "本轮工具返回了候选商品，<R> 中至少需要包含 1 个推荐商品 ID。",
                raw_output=text,
                details={"candidate_ids": sorted(candidate_ids)},
            )
        return ParsedFinalResponse(recommended_ids, None, clean_text)

    if compare_matches:
        compare_match = compare_matches[0]
        _ensure_marker_is_first_line(text, compare_match, "<C>")
        compare_payload = _loads_compare_payload_or_raise(
            compare_match.group(1),
            raw_output=text,
        )
        return ParsedFinalResponse([], compare_payload, clean_text)

    return ParsedFinalResponse([], None, text)


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


def _strip_hidden_event_marker_text(text: str) -> str:
    text = re.sub(r"<R>.*?</R>\n?", "", text, flags=re.DOTALL)
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


def _parse_recommend_ids(ids_str: str) -> list[str]:
    ids_str = ids_str.strip()
    return [pid.strip() for pid in ids_str.split(",") if pid.strip()] if ids_str else []


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
