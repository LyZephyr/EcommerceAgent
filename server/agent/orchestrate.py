"""Agent turn orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import conversation
from agent.contracts import AgentState, TurnBudget
from agent.errors import RecoveryState
from agent.events import (
    BlockCompareEvent,
    BlockProductEvent,
    BlockTextDeltaEvent,
    BlockTextEvent,
    CartEvent,
    MessageCommitEvent,
    MessageResetEvent,
    MessageStartEvent,
    StructuredStatusEvent,
)
from agent.prompts import SYSTEM_PROMPT
from agent.runtime import model_step, tool_step, use_event_emitter
from config import ARK_API_KEY

AgentEvent = (
    CartEvent
    | BlockTextEvent
    | BlockTextDeltaEvent
    | BlockProductEvent
    | BlockCompareEvent
    | MessageStartEvent
    | MessageResetEvent
    | MessageCommitEvent
    | StructuredStatusEvent
)


async def run_turn(
    conversation_id: str,
    user_message: str,
) -> AsyncIterator[AgentEvent]:
    """Run one chat turn and yield AgentEvent objects for SSE mapping."""
    if not ARK_API_KEY:
        raise RuntimeError(
            "缺少 ARK_API_KEY，请在项目根目录 .env 中配置正确的 API Key。"
        )

    state = build_initial_state(conversation_id, user_message)
    while state["route"] != "done":
        step = model_step if state["route"] == "model" else tool_step
        update: dict[str, Any] | None = None
        async for item in _run_step_with_events(step, state):
            if isinstance(item, dict):
                update = item
                continue
            yield item
        if update is None:
            raise RuntimeError("Agent step finished without a state update.")
        state.update(update)


def build_initial_state(conversation_id: str, user_message: str) -> AgentState:
    conversation.append(conversation_id, {"role": "user", "content": user_message})
    history = conversation.get_history(conversation_id)
    return {
        "conversation_id": conversation_id,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *history],
        "candidates_by_id": {},
        "candidate_groups": [],
        "recovery": RecoveryState(),
        "budget": TurnBudget(),
        "used_retrieve_tool": False,
        "message_id": f"asst-{uuid4().hex}",
        "attempt_index": 1,
        "tool_step_count": 0,
        "pending_tool_calls": [],
        "route": "model",
        "force_final": False,
    }


async def _run_step_with_events(step, state: AgentState):
    queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
    task: asyncio.Task[dict[str, Any]] | None = None
    with use_event_emitter(queue.put_nowait):
        task = asyncio.create_task(step(state))
        try:
            while True:
                event_task = asyncio.create_task(queue.get())
                done, _pending = await asyncio.wait(
                    {task, event_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if event_task in done:
                    yield event_task.result()
                    if not task.done():
                        continue
                else:
                    event_task.cancel()
                    await asyncio.gather(event_task, return_exceptions=True)

                if task in done:
                    while not queue.empty():
                        yield queue.get_nowait()
                    yield task.result()
                    return
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


