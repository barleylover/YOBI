TOOLS = [
    {
        "type": "function",
        "name": "recommend_menu_categories",
        "description": "Recommend 2-4 grounded synthetic menu categories after hard constraints.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "budget_krw": {"type": ["integer", "null"]},
                "max_spiciness": {"type": ["integer", "null"], "minimum": 0, "maximum": 5},
                "excluded_ingredients": {"type": "array", "items": {"type": "string"}},
                "servings": {"type": "integer", "minimum": 1, "maximum": 10},
                "desired_temperature": {"type": "string", "enum": ["warm", "cold", "any"]},
                "desired_texture": {"type": "array", "items": {"type": "string"}},
                "desired_flavors": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query", "budget_krw", "max_spiciness", "excluded_ingredients", "servings", "desired_temperature", "desired_texture", "desired_flavors"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_menus",
        "description": "Search the synthetic menu catalog with server-enforced constraints.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "budget_krw": {"type": ["integer", "null"]},
                "max_spiciness": {"type": ["integer", "null"], "minimum": 0, "maximum": 5},
                "excluded_ingredients": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query", "budget_krw", "max_spiciness", "excluded_ingredients"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "explain_menu",
        "description": "Explain one real seeded menu with cultural analogy and evidence IDs.",
        "parameters": {
            "type": "object",
            "properties": {"menu_id": {"type": "string"}},
            "required": ["menu_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_dietary_evidence",
        "description": "Retrieve source-linked dietary evidence for a seeded menu.",
        "parameters": {
            "type": "object",
            "properties": {"menu_id": {"type": "string"}},
            "required": ["menu_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "compare_merchants",
        "description": "Compare merchants on shared seeded axes for a menu category.",
        "parameters": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": ["category"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_menu_options",
        "description": "Load authoritative option groups and price deltas for a menu.",
        "parameters": {
            "type": "object",
            "properties": {"menu_id": {"type": "string"}},
            "required": ["menu_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "translate_order_note",
        "description": "Translate an order or courier note and return a back translation for confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_note": {"type": "string"},
                "target_context": {"type": "string", "enum": ["restaurant", "courier"]},
                "tone": {"type": "string", "enum": ["polite", "concise"]},
            },
            "required": ["user_note", "target_context", "tone"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "resolve_address",
        "description": "Resolve a hotel name or OCR text to synthetic address candidates; never auto-confirm.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "update_cart",
        "description": "Apply an explicit user cart request. The server validates options and recalculates every price.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["ADD_ITEM", "CHANGE_QUANTITY", "SELECT_OPTION", "REMOVE_OPTION", "REMOVE_ITEM", "ADD_NOTE", "CLEAR"]},
                "menu_id": {"type": ["string", "null"]},
                "cart_item_id": {"type": ["string", "null"]},
                "quantity": {"type": ["integer", "null"], "minimum": 1, "maximum": 10},
                "option_item_id": {"type": ["string", "null"]},
                "option_item_ids": {"type": "array", "items": {"type": "string"}},
                "note": {"type": ["string", "null"]},
            },
            "required": ["action", "menu_id", "cart_item_id", "quantity", "option_item_id", "option_item_ids", "note"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "update_delivery_preferences",
        "description": "Save explicit synthetic-delivery handoff preferences; the address still requires user confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "address_ref_id": {"type": ["string", "null"]},
                "handoff_method": {"type": "string", "enum": ["front_desk", "door", "meet_outside"]},
                "cutlery": {"type": "boolean"},
                "ring_bell": {"type": "boolean"},
                "front_desk": {"type": "boolean"},
                "note": {"type": "string"},
            },
            "required": ["address_ref_id", "handoff_method", "cutlery", "ring_bell", "front_desk", "note"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_cart_preview",
        "description": "Read the server-calculated cart snapshot and missing required slots.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_mock_payment_status",
        "description": "Read a synthetic checkout status without changing payment or order state.",
        "parameters": {
            "type": "object",
            "properties": {"checkout_id": {"type": "string"}},
            "required": ["checkout_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "create_mock_checkout",
        "description": "Create an idempotent demo checkout only after the user-confirmed cart passes server revalidation.",
        "parameters": {
            "type": "object",
            "properties": {
                "idempotency_key": {"type": "string"},
                "payment_method": {"type": "string", "enum": ["international_card", "apple_pay_demo", "paypal_demo"]},
            },
            "required": ["idempotency_key", "payment_method"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "complete_mock_order",
        "description": "Return the one existing demo order after payment succeeds; never marks payment successful itself.",
        "parameters": {
            "type": "object",
            "properties": {"checkout_id": {"type": "string"}},
            "required": ["checkout_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def select_tools(user_text: str) -> list[dict[str, object]]:
    """Route a turn to a small allowlisted tool surface.

    Sending every schema on every turn needlessly consumes the provider's request
    token quota. The complete 14-tool contract remains registered above; this
    deterministic router exposes only the tools relevant to the user's current
    action and never uses model-generated routing policy.
    """
    lowered = user_text.lower()
    if any(term in lowered for term in ("pay", "payment", "checkout", "order status")):
        names = {
            "get_cart_preview",
            "create_mock_checkout",
            "get_mock_payment_status",
            "complete_mock_order",
        }
    elif any(term in lowered for term in ("address", "hotel", "deliver", "front desk")):
        names = {"resolve_address", "update_delivery_preferences", "get_cart_preview"}
    elif any(term in lowered for term in ("option", "size", "spice level", "add to cart", "note")):
        names = {"get_menu_options", "update_cart", "translate_order_note", "get_cart_preview"}
    elif any(term in lowered for term in ("compare", "cheapest", "fastest", "restaurant")):
        names = {"search_menus", "compare_merchants", "get_dietary_evidence"}
    elif any(term in lowered for term in ("allergy", "shellfish", "red rice", "tteokbokki")):
        names = {"search_menus", "explain_menu", "get_dietary_evidence"}
    else:
        names = {"recommend_menu_categories", "search_menus", "explain_menu"}
    return [tool for tool in TOOLS if str(tool["name"]) in names]
