"""Agent 模块常量。"""

from __future__ import annotations

import re

MAX_TOOL_STEPS = 3
MAX_RECOVERY_RETRIES = 2
MAX_TOTAL_RECOVERY_ATTEMPTS = 6
LLM_TIMEOUT_SECONDS = 60
LOG_ARGUMENTS_MAX_CHARS = 4000
LOG_TOOL_RESULT_MAX_CHARS = 100
LOG_LLM_OUTPUT_MAX_CHARS = 4000
MARKER_TAG_RE = re.compile(r"</?(?:R|C)(?:\s[^>]*)?>")
MOBILE_VISIBLE_REPLY_MAX_CHARS = 120
VISIBLE_MARKDOWN_TOKEN_RE = re.compile(r"###|\*\*|\||(^|\n)\s*-{3,}\s*$", re.MULTILINE)
RECOMMEND_FIELD_LIMITS = {"INTRO": 40, "REASON": 45, "OUTRO": 40}
ITEM_ATTR_VALUE_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff\-_\s:/]+$")
ITEM_OPEN_TAG_RE = re.compile(
    r'<ITEM\s+id="([^"<>\\]*)"(?:\s+group="([^"<>\\]*)")?\s*>'
)
