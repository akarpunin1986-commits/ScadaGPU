"""
САНЁК v4 — Convert Anthropic tool definitions to OpenAI format.

Handles GPT-5.4 strict mode requirements RECURSIVELY:
- additionalProperties: false on ALL objects
- ALL properties in required
- Optional params → nullable via anyOf
- No unsupported keywords
"""
from __future__ import annotations

import copy


def convert_tools_to_openai(anthropic_tools: list[dict]) -> list[dict]:
    """Convert Anthropic-format tool definitions to OpenAI strict mode format."""
    openai_tools = []
    for tool in anthropic_tools:
        schema = _fix_schema_recursive(copy.deepcopy(tool.get("input_schema", {})),
                                        required_set=set(tool.get("input_schema", {}).get("required", [])))

        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", "")[:1024],
                "parameters": schema,
                "strict": True,
            },
        })
    return openai_tools


def _fix_schema_recursive(schema: dict, required_set: set | None = None) -> dict:
    """
    Recursively fix schema for OpenAI strict mode.

    Rules:
    1. Every object must have additionalProperties: false
    2. ALL properties must be listed in required
    3. Optional params get anyOf: [{original_type}, {"type": "null"}]
    4. Remove unsupported keywords (default, examples, minimum, maximum, enum on non-string)
    5. Recurse into nested objects and array items
    """
    if not isinstance(schema, dict):
        return schema

    schema = dict(schema)
    schema_type = schema.get("type")

    # Handle object types
    if schema_type == "object" or "properties" in schema:
        schema["type"] = "object"
        schema["additionalProperties"] = False

        props = schema.get("properties", {})
        orig_required = set(schema.get("required", []))
        if required_set is not None:
            orig_required = required_set

        new_props = {}
        for prop_name, prop_def in props.items():
            prop_def = dict(prop_def)

            # Remove unsupported keywords
            for bad_key in ("examples", "default", "minimum", "maximum"):
                prop_def.pop(bad_key, None)

            # Recurse into nested objects
            prop_type = prop_def.get("type")
            if prop_type == "object" or "properties" in prop_def:
                nested_required = set(prop_def.get("required", []))
                prop_def = _fix_schema_recursive(prop_def, required_set=nested_required)

            # Fix array items
            if prop_type == "array" and "items" in prop_def:
                prop_def["items"] = _fix_schema_recursive(dict(prop_def["items"]))

            # Ensure type exists
            if "type" not in prop_def and "anyOf" not in prop_def:
                prop_def["type"] = "string"

            # Optional params → anyOf with null
            if prop_name not in orig_required:
                ptype = prop_def.get("type")
                if ptype and ptype != "null":
                    if isinstance(ptype, list):
                        if "null" not in ptype:
                            prop_def["type"] = ptype + ["null"]
                    elif isinstance(ptype, str):
                        # Use anyOf for complex types, simple union for primitives
                        if ptype in ("string", "integer", "number", "boolean"):
                            prop_def["type"] = [ptype, "null"]
                        else:
                            # For object/array, wrap in anyOf
                            null_schema = {"type": "null"}
                            original = {k: v for k, v in prop_def.items() if k != "description"}
                            desc = prop_def.get("description")
                            prop_def = {"anyOf": [original, null_schema]}
                            if desc:
                                prop_def["description"] = desc

            new_props[prop_name] = prop_def

        schema["properties"] = new_props
        schema["required"] = list(new_props.keys())  # ALL required in strict mode

    # Handle array type
    elif schema_type == "array" and "items" in schema:
        schema["items"] = _fix_schema_recursive(dict(schema["items"]))

    # Ensure type exists for leaf nodes
    if "type" not in schema and "anyOf" not in schema:
        schema["type"] = "string"

    return schema
