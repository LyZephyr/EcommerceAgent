"""流式最终回复解析与块事件发射。"""

from __future__ import annotations

import time

from agent.errors import RecoverableAgentError
from agent.events import (
    BlockCompareEvent,
    BlockProductEvent,
    BlockTextDeltaEvent,
    ParsedFinalResponse,
    RecommendationItem,
)
from agent.logging_utils import elapsed_ms
from agent.parsing.final import parse_final_response
from agent.parsing.recommend import parse_recommendation_item_tag


def split_text_delta(text: str) -> list[str]:
    parts: list[str] = []
    index = 0
    while index < len(text):
        step = 1 if _is_cjk(text[index]) else 3
        parts.append(text[index : index + step])
        index += step
    return parts


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


class StreamingFinalEmitter:
    def __init__(
        self,
        *,
        message_id: str,
        attempt_id: str,
        candidates_by_id: dict[str, dict],
        candidate_groups: list[dict],
    ) -> None:
        self.message_id = message_id
        self.attempt_id = attempt_id
        self.candidates_by_id = candidates_by_id
        self.candidate_ids = set(candidates_by_id)
        self.candidate_groups = candidate_groups
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
        self.pending_recommendation_whitespace = ""

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
            return parse_final_response(
                self.raw_output,
                candidate_ids=self.candidate_ids,
                candidate_groups=self.candidate_groups,
            )
        return parse_final_response(
            self.raw_output,
            candidate_ids=self.candidate_ids,
            candidate_groups=self.candidate_groups,
        )

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
        self.mode = "text"
        return self._emit_normal_text(self.buffer)

    def _drain_recommendation(
        self,
    ) -> list[BlockTextDeltaEvent | BlockProductEvent]:
        events: list[BlockTextDeltaEvent | BlockProductEvent] = []
        while self.buffer:
            if self.state == "await_child":
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

        return events

    def _handle_recommendation_tag(
        self,
        tag: str,
    ) -> list[BlockProductEvent]:
        self.pending_recommendation_whitespace = ""
        if tag == "<INTRO>" and self.state == "await_child" and not self.intro and not self.items:
            self.current_block_id = self._next_block_id()
            self.state = "intro_text"
            return []
        if tag.startswith("<ITEM ") and self.state in {"intro_text", "reason_text"}:
            if self.state == "reason_text" and self.current_item:
                self.items.append(self.current_item)
            item = parse_recommendation_item_tag(
                tag,
                raw_output=self.raw_output,
                candidate_ids=self.candidate_ids,
                candidate_groups=self.candidate_groups,
            )
            product = self.candidates_by_id[item.product_id]
            self.current_item = item
            product_block_id = self._next_block_id()
            self.current_block_id = self._next_block_id()
            self.state = "reason_text"
            return [
                BlockProductEvent(
                    message_id=self.message_id,
                    block_id=product_block_id,
                    product_id=item.product_id,
                    product_data=product,
                    group=item.group,
                    attempt_id=self.attempt_id,
                )
            ]
        if tag == "<OUTRO>" and self.state == "reason_text" and self.current_item:
            self.items.append(self.current_item)
            self.current_item = None
            self.current_block_id = self._next_block_id()
            self.state = "outro_text"
            return []
        raise RecoverableAgentError(
            "recommend_marker_invalid",
            "推荐标记顺序或嵌套不合法。",
            raw_output=self.raw_output,
            details={"tag": tag, "state": self.state},
        )

    def _emit_recommendation_text(self, text: str) -> list[BlockTextDeltaEvent]:
        if not text:
            return []
        text = self._recommendation_text_delta(text)
        if not text:
            return []
        if self.state == "intro_text":
            self.intro += text
        elif self.state == "reason_text" and self.current_item:
            self.current_item.reason += text
        elif self.state == "outro_text":
            self.outro = (self.outro or "") + text
        return self._emit_text_delta(text, self.current_block_id)

    def _recommendation_text_delta(self, text: str) -> str:
        current_text = self._current_recommendation_text()
        if not current_text:
            text = text.lstrip()
            self.pending_recommendation_whitespace = ""
        else:
            text = self.pending_recommendation_whitespace + text
            self.pending_recommendation_whitespace = ""

        if not text:
            return ""

        trimmed = text.rstrip()
        self.pending_recommendation_whitespace = text[len(trimmed) :]
        return trimmed

    def _current_recommendation_text(self) -> str:
        if self.state == "intro_text":
            return self.intro
        if self.state == "reason_text" and self.current_item:
            return self.current_item.reason
        if self.state == "outro_text":
            return self.outro or ""
        return ""

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
                attempt_id=self.attempt_id,
            )
            for part in split_text_delta(text)
        ]

    def _next_block_id(self) -> str:
        block_id = f"blk-{self.block_index}"
        self.block_index += 1
        return block_id

    def _record_first_visible(self) -> None:
        if self.first_visible_ms is None:
            self.first_visible_ms = elapsed_ms(self.started_at)
