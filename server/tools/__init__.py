"""Agent 工具注册表。"""

from tools.retrieve_products import TOOL_DEFINITION, execute as _retrieve_execute

TOOL_DEFINITIONS = [TOOL_DEFINITION]

_EXECUTORS = {"retrieve_products": _retrieve_execute}


def execute(name: str, arguments: dict) -> list[dict]:
    return _EXECUTORS[name](arguments)
