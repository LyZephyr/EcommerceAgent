"""Agent 工具注册表。"""

from tools.cart import TOOL_DEFINITIONS as CART_TOOL_DEFINITIONS
from tools.cart import execute as _cart_execute
from tools.retrieve_products import TOOL_DEFINITION as RETRIEVE_TOOL_DEFINITION
from tools.retrieve_products import execute as _retrieve_execute

TOOL_DEFINITIONS = [RETRIEVE_TOOL_DEFINITION, *CART_TOOL_DEFINITIONS]

_EXECUTORS = {"retrieve_products": _retrieve_execute}
_CART_TOOL_NAMES = {
    "add_to_cart",
    "list_recent_products",
    "remove_from_cart",
    "update_cart_item",
    "view_cart",
    "clear_cart",
}


def execute(name: str, arguments: dict, conversation_id: str | None = None):
    if name in _CART_TOOL_NAMES:
        if conversation_id is None:
            raise ValueError("购物车工具需要 conversation_id。")
        return _cart_execute(name, arguments, conversation_id)
    return _EXECUTORS[name](arguments)
