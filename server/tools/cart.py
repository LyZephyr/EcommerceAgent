"""购物车工具：把自然语言购物车意图映射为确定性的状态操作。"""

from __future__ import annotations

import cart_store

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": (
                "把最近展示过的商品加入购物车。"
                "用户说“第一款/第二个”时填写 recent_position；"
                "用户提到商品名、品牌或品类时填写 title_keyword；"
                "只有用户明确给出商品 ID 时才填写 product_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "商品 ID"},
                    "recent_position": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "最近展示商品列表中的 1-based 位置",
                    },
                    "title_keyword": {
                        "type": "string",
                        "description": "商品标题、品牌、类目中的关键词",
                    },
                    "quantity": {
                        "type": "integer",
                        "minimum": 1,
                        "default": 1,
                        "description": "加购数量",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": (
                "从购物车删除商品。用户说“购物车第二个”时填写 cart_position；"
                "提到商品名、品牌或品类时填写 title_keyword。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "商品 ID"},
                    "cart_position": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "购物车明细中的 1-based 位置",
                    },
                    "title_keyword": {
                        "type": "string",
                        "description": "商品标题、品牌、类目中的关键词",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_cart_item",
            "description": (
                "修改购物车中某个商品的数量。用户说“购物车第二个”时填写 cart_position；"
                "提到商品名、品牌或品类时填写 title_keyword。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "商品 ID"},
                    "cart_position": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "购物车明细中的 1-based 位置",
                    },
                    "title_keyword": {
                        "type": "string",
                        "description": "商品标题、品牌、类目中的关键词",
                    },
                    "quantity": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "目标数量",
                    },
                },
                "required": ["quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_cart",
            "description": "查看当前会话购物车状态。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_cart",
            "description": "清空当前会话购物车。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute(name: str, arguments: dict, conversation_id: str) -> dict:
    if name == "add_to_cart":
        return _add_to_cart(arguments, conversation_id)
    if name == "remove_from_cart":
        return _remove_from_cart(arguments, conversation_id)
    if name == "update_cart_item":
        return _update_cart_item(arguments, conversation_id)
    if name == "view_cart":
        return _view_cart(conversation_id)
    if name == "clear_cart":
        return _clear_cart(conversation_id)
    raise KeyError(name)


def _add_to_cart(arguments: dict, conversation_id: str) -> dict:
    quantity = int(arguments.get("quantity") or 1)
    if quantity < 1:
        return _error("加购数量必须至少为 1。")

    product, error = _resolve_recent_product(arguments, conversation_id)
    if error:
        return _error(error)

    try:
        cart = cart_store.add_item(conversation_id, product, quantity)
    except cart_store.CartOperationError as exc:
        return _error(str(exc))

    item = _cart_item_by_id(cart, product["product_id"]) or product
    return _success(
        cart,
        _with_cart_messages(
            f"已将「{item['title']}」加入购物车，数量 {quantity} 件。{_summary(cart)}",
            cart,
        ),
    )


def _remove_from_cart(arguments: dict, conversation_id: str) -> dict:
    item, error = _resolve_cart_item(arguments, conversation_id)
    if error:
        return _error(error)

    cart = cart_store.remove_item(conversation_id, item["product_id"])
    return _success(cart, f"已从购物车删除「{item['title']}」。{_summary(cart)}")


def _update_cart_item(arguments: dict, conversation_id: str) -> dict:
    quantity = int(arguments["quantity"])
    if quantity < 1:
        return _error("商品数量必须至少为 1。")

    item, error = _resolve_cart_item(arguments, conversation_id)
    if error:
        return _error(error)

    try:
        cart = cart_store.update_item(conversation_id, item["product_id"], quantity)
    except cart_store.CartOperationError as exc:
        return _error(str(exc))

    latest_item = _cart_item_by_id(cart, item["product_id"]) or item
    return _success(
        cart,
        _with_cart_messages(
            f"已把「{latest_item['title']}」数量改为 {quantity} 件。{_summary(cart)}",
            cart,
        ),
    )


def _view_cart(conversation_id: str) -> dict:
    cart = cart_store.snapshot(conversation_id)
    if not cart["items"]:
        return _success(cart, _with_cart_messages("购物车还是空的。", cart))

    lines = [
        f"{index}. {item['title']} x {item['quantity']}，¥{item['price']:.2f}"
        for index, item in enumerate(cart["items"], start=1)
    ]
    message = "购物车里有：\n" + "\n".join(lines) + f"\n{_summary(cart)}"
    return _success(cart, _with_cart_messages(message, cart))


def _clear_cart(conversation_id: str) -> dict:
    cart = cart_store.clear_cart(conversation_id)
    return _success(cart, "已清空购物车。")


def _resolve_recent_product(arguments: dict, conversation_id: str) -> tuple[dict, str | None]:
    product_id = arguments.get("product_id")
    if product_id:
        product = cart_store.get_recent_product(conversation_id, str(product_id))
        if product:
            return product, None
        return {}, "这个商品不在当前会话最近展示的商品里，不能加入购物车。"

    recent_position = arguments.get("recent_position")
    if recent_position is not None:
        product = cart_store.get_recent_product_by_position(
            conversation_id,
            int(recent_position),
        )
        if product:
            return product, None
        return {}, "最近展示的商品里没有这个位置，请重新说明要加购哪一款。"

    recent_products = cart_store.list_recent_products(conversation_id)
    keyword = arguments.get("title_keyword")
    if keyword:
        return _match_one(recent_products, keyword, "最近展示商品")

    if len(recent_products) == 1:
        return recent_products[0], None
    if not recent_products:
        return {}, "当前还没有可加入购物车的已展示商品。"
    return {}, "你想加购哪一款？请说明第几个商品或商品名。"


def _resolve_cart_item(arguments: dict, conversation_id: str) -> tuple[dict, str | None]:
    cart = cart_store.snapshot(conversation_id)
    items = cart["items"]
    if not items:
        return {}, "购物车还是空的。"

    product_id = arguments.get("product_id")
    if product_id:
        for item in items:
            if item["product_id"] == str(product_id):
                return item, None
        return {}, "购物车中不存在这个商品。"

    cart_position = arguments.get("cart_position")
    if cart_position is not None:
        index = int(cart_position) - 1
        if 0 <= index < len(items):
            return items[index], None
        return {}, "购物车里没有这个位置的商品。"

    keyword = arguments.get("title_keyword")
    if keyword:
        return _match_one(items, keyword, "购物车商品")

    if len(items) == 1:
        return items[0], None
    return {}, "你想操作购物车里的哪一款？请说明第几个商品或商品名。"


def _match_one(items: list[dict], keyword: str, source_name: str) -> tuple[dict, str | None]:
    normalized_keyword = _normalize(keyword)
    matches = [
        item
        for item in items
        if normalized_keyword
        and any(
            normalized_keyword in _normalize(str(item.get(field) or ""))
            for field in ("title", "brand", "category", "sub_category")
        )
    ]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return {}, f"没有找到匹配“{keyword}”的{source_name}。"
    return {}, f"找到多款匹配“{keyword}”的{source_name}，请说明第几个或完整商品名。"


def _normalize(value: str) -> str:
    return "".join(value.lower().split())


def _success(cart: dict, message: str) -> dict:
    return {"success": True, "message": message, "cart": cart}


def _error(message: str) -> dict:
    return {"success": False, "message": message}


def _summary(cart: dict) -> str:
    return f"当前共 {cart['total_quantity']} 件，合计 ¥{cart['total_price']:.2f}。"


def _cart_item_by_id(cart: dict, product_id: str) -> dict | None:
    for item in cart["items"]:
        if item["product_id"] == product_id:
            return item
    return None


def _with_cart_messages(message: str, cart: dict) -> str:
    messages = cart.get("messages") or []
    if not messages:
        return message
    return message + "\n" + "\n".join(messages)
