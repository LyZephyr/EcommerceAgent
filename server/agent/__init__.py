"""Agent 编排：LangGraph 工具流 + 最终回复解析。"""

from agent.candidates import candidate_group_product_ids
from agent.contracts import (
    CandidateGroup,
    CandidateProduct,
    RecentProductEntry,
    ToolCall,
    TurnBudget,
)
from agent.errors import AgentRecoveryExhausted, RecoverableAgentError, RecoveryState
from agent.events import (
    BlockCompareEvent,
    BlockProductEvent,
    BlockTextDeltaEvent,
    BlockTextEvent,
    CartEvent,
    MessageCommitEvent,
    MessageResetEvent,
    MessageStartEvent,
    ParsedFinalResponse,
    ParsedRecommendation,
    RecommendationItem,
    StructuredStatusEvent,
)
from agent.orchestrate import run_turn
from agent.parsing.final import parse_final_response
from agent.prompts import FINAL_REPLY_PROMPT, SYSTEM_PROMPT, TOOL_USE_PROMPT
from agent.streaming import StreamingFinalEmitter
from agent.emitters import events_from_parsed_response, recommendation_history_text

__all__ = [
    "AgentRecoveryExhausted",
    "BlockCompareEvent",
    "BlockProductEvent",
    "BlockTextDeltaEvent",
    "BlockTextEvent",
    "CartEvent",
    "CandidateGroup",
    "CandidateProduct",
    "FINAL_REPLY_PROMPT",
    "MessageCommitEvent",
    "MessageResetEvent",
    "MessageStartEvent",
    "ParsedFinalResponse",
    "ParsedRecommendation",
    "RecentProductEntry",
    "RecommendationItem",
    "RecoverableAgentError",
    "RecoveryState",
    "StructuredStatusEvent",
    "SYSTEM_PROMPT",
    "TOOL_USE_PROMPT",
    "ToolCall",
    "TurnBudget",
    "StreamingFinalEmitter",
    "candidate_group_product_ids",
    "events_from_parsed_response",
    "parse_final_response",
    "recommendation_history_text",
    "run_turn",
]
