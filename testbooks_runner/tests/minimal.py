"""The smallest JSON instance that fits a JSON schema, for a fake model that must answer without reading."""
from __future__ import annotations

from typing import Any


def minimal_instance(schema: dict, _root: dict | None = None) -> Any:
    root = schema if _root is None else _root
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return minimal_instance(node, root)
    for key in ("anyOf", "oneOf"):
        if schema.get(key):
            return minimal_instance(schema[key][0], root)
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), kind[0])
    if kind == "object" or (kind is None and "properties" in schema):
        props = schema.get("properties", {})
        return {name: minimal_instance(props.get(name, {}), root) for name in schema.get("required", [])}
    if kind == "array":
        return [minimal_instance(schema.get("items", {}), root) for _ in range(schema.get("minItems", 0))]
    if kind == "string":
        return "1970-01-01" if schema.get("format") == "date" else ""
    if kind in ("number", "integer"):
        return 0
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return None
