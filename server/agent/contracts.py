"""Typed contracts used inside the Agent runtime boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, TypedDict

from agent.constants import (
    MAX_RECOVERY_RETRIES,
    MAX_TOOL_STEPS,
    MAX_TOTAL_RECOVERY_ATTEMPTS,
)
from agent.errors import AgentRecoveryExhausted, RecoverableAgentError, RecoveryState


@dataclass(frozen=True)
class CandidateProduct:
    data: dict[str, Any]

    @property
    def product_id(self) -> str:
        return str(self.data["product_id"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


@dataclass(frozen=True)
class CandidateGroup:
    label: str | None
    search_query: str | None
    products: list[CandidateProduct]

    @classmethod
    def from_mapping(cls, group: dict[str, Any]) -> CandidateGroup:
        return cls(
            label=group.get("label"),
            search_query=group.get("search_query"),
            products=[
                CandidateProduct(dict(product))
                for product in group.get("products", [])
                if product.get("product_id")
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "search_query": self.search_query,
            "products": [product.to_dict() for product in self.products],
        }


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str
    type: str = "function"

    @classmethod
    def from_mapping(cls, tool_call: dict[str, Any]) -> ToolCall:
        function = tool_call.get("function") or {}
        return cls(
            id=str(tool_call.get("id") or ""),
            type=str(tool_call.get("type") or "function"),
            name=str(function.get("name") or ""),
            arguments=str(function.get("arguments") or "{}"),
        )

    def to_openai_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass(frozen=True)
class RecentProductEntry:
    product_data: dict[str, Any]
    group: str | None = None


@dataclass(frozen=True)
class TurnBudget:
    model_steps: int = 0
    tool_steps: int = 0
    transitions: int = 0
    force_final_attempted: bool = False
    max_model_steps: int = MAX_TOOL_STEPS + MAX_TOTAL_RECOVERY_ATTEMPTS + 3
    max_tool_steps: int = MAX_TOOL_STEPS
    max_transitions: int = MAX_TOOL_STEPS * 2 + MAX_RECOVERY_RETRIES + 8

    def record_model_step(self, *, force_final: bool) -> TurnBudget:
        budget = replace(
            self,
            model_steps=self.model_steps + 1,
            transitions=self.transitions + 1,
        )
        if force_final:
            if budget.force_final_attempted:
                budget._raise_exhausted("force_final_repeated")
            budget = replace(budget, force_final_attempted=True)
        budget._ensure_within_limits()
        return budget

    def record_tool_step(self) -> TurnBudget:
        budget = replace(
            self,
            tool_steps=self.tool_steps + 1,
            transitions=self.transitions + 1,
        )
        budget._ensure_within_limits()
        return budget

    def _ensure_within_limits(self) -> None:
        if self.model_steps > self.max_model_steps:
            self._raise_exhausted("model_step_budget_exceeded")
        if self.tool_steps > self.max_tool_steps:
            self._raise_exhausted("tool_step_budget_exceeded")
        if self.transitions > self.max_transitions:
            self._raise_exhausted("transition_budget_exceeded")

    def _raise_exhausted(self, error_type: str) -> None:
        error = RecoverableAgentError(
            error_type,
            "Agent turn budget exhausted before reaching a terminal state.",
            details={
                "model_steps": self.model_steps,
                "tool_steps": self.tool_steps,
                "transitions": self.transitions,
                "force_final_attempted": self.force_final_attempted,
                "max_model_steps": self.max_model_steps,
                "max_tool_steps": self.max_tool_steps,
                "max_transitions": self.max_transitions,
            },
        )
        raise AgentRecoveryExhausted(error, self.transitions) from error


class AgentState(TypedDict, total=False):
    conversation_id: str
    messages: list[dict[str, Any]]
    candidates_by_id: dict[str, CandidateProduct]
    candidate_groups: list[CandidateGroup]
    recovery: RecoveryState
    budget: TurnBudget
    used_retrieve_tool: bool
    message_id: str
    attempt_index: int
    tool_step_count: int
    pending_tool_calls: list[ToolCall]
    route: Literal["model", "tools", "done"]
    force_final: bool


def candidate_groups_from_tool_result(groups: list[dict[str, Any]]) -> list[CandidateGroup]:
    return [CandidateGroup.from_mapping(group) for group in groups]


def candidate_groups_to_dicts(groups: list[CandidateGroup]) -> list[dict[str, Any]]:
    return [group.to_dict() for group in groups]


def candidates_to_dicts(
    candidates_by_id: dict[str, CandidateProduct],
) -> dict[str, dict[str, Any]]:
    return {
        product_id: product.to_dict()
        for product_id, product in candidates_by_id.items()
    }


def flatten_candidate_group_products(
    groups: list[CandidateGroup],
) -> list[CandidateProduct]:
    candidates: list[CandidateProduct] = []
    seen_ids: set[str] = set()
    for group in groups:
        for product in group.products:
            if product.product_id in seen_ids:
                continue
            seen_ids.add(product.product_id)
            candidates.append(product)
    return candidates
