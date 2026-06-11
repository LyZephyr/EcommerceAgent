"""Agent 编排：ReAct 工具循环 + 最终回复解析。"""

from agent.candidates import candidate_group_product_ids
from agent.errors import AgentRecoveryExhausted, RecoverableAgentError, RecoveryState
from agent.events import (
    BlockCompareEvent,
    BlockProductEvent,
    BlockTextDeltaEvent,
    BlockTextEvent,
    CartEvent,
    ParsedFinalResponse,
    ParsedRecommendation,
    RecommendationItem,
    StructuredStatusEvent,
)
from agent.loop import run_turn
from agent.parsing.final import parse_final_response
from agent.prompts import FINAL_REPLY_PROMPT, SYSTEM_PROMPT, TOOL_USE_PROMPT
from agent.streaming import StreamingFinalEmitter
from agent.tools_helpers import parse_tool_call
from agent.emitters import events_from_parsed_response, recommendation_history_text

# 测试与内部模块使用的私有符号别名，保持 refactor 前后 import 兼容。
_StreamingFinalEmitter = StreamingFinalEmitter
_events_from_parsed_response = events_from_parsed_response
_parse_final_response = parse_final_response
_parse_tool_call = parse_tool_call
_recommendation_history_text = recommendation_history_text
_candidate_group_product_ids = candidate_group_product_ids

__all__ = [
    "AgentRecoveryExhausted",
    "BlockCompareEvent",
    "BlockProductEvent",
    "BlockTextDeltaEvent",
    "BlockTextEvent",
    "CartEvent",
    "FINAL_REPLY_PROMPT",
    "ParsedFinalResponse",
    "ParsedRecommendation",
    "RecommendationItem",
    "RecoverableAgentError",
    "RecoveryState",
    "StructuredStatusEvent",
    "SYSTEM_PROMPT",
    "TOOL_USE_PROMPT",
    "_StreamingFinalEmitter",
    "_candidate_group_product_ids",
    "_events_from_parsed_response",
    "_parse_final_response",
    "_parse_tool_call",
    "_recommendation_history_text",
    "run_turn",
]
