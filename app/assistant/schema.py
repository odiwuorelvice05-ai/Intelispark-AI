"""Minimal JSON-schema validation/coercion for model-supplied tool arguments.

Models send numbers as strings, invent extra keys and omit fields. This coerces what it
safely can, drops what it does not recognise, and reports what is missing or invalid, so
one sloppy argument costs a corrective tool result rather than a failed conversation.
"""
from __future__ import annotations

from typing import Any


def _coerce(value: Any, spec: dict[str, Any], path: str, errors: list[str]) -> Any:
    kind = spec.get("type")
    if kind == "string":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            errors.append(f"{path}: expected a string")
            return None
        value = value.strip()
        if "enum" in spec:
            match = next((e for e in spec["enum"] if e.lower() == value.lower()), None)
            if match is None:
                errors.append(f"{path}: must be one of {spec['enum']}")
            return match
        return value[: spec.get("maxLength", 500)]
    if kind in ("integer", "number"):
        if isinstance(value, str):
            try:
                value = float(value.replace(",", "").strip())
            except ValueError:
                errors.append(f"{path}: expected a number")
                return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{path}: expected a number")
            return None
        if kind == "integer":
            if float(value) != int(value):
                errors.append(f"{path}: expected an integer")
                return None
            value = int(value)
        if "minimum" in spec and value < spec["minimum"]:
            errors.append(f"{path}: must be >= {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            errors.append(f"{path}: must be <= {spec['maximum']}")
        return value
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        errors.append(f"{path}: expected true or false")
        return None
    if kind == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: expected a list")
            return None
        if len(value) > spec.get("maxItems", 50):
            errors.append(f"{path}: at most {spec['maxItems']} items")
            return None
        if len(value) < spec.get("minItems", 0):
            errors.append(f"{path}: at least {spec['minItems']} items")
            return None
        items = [_coerce(v, spec.get("items", {"type": "string"}), f"{path}[]", errors) for v in value]
        return [i for i in items if i is not None]
    if kind == "object":
        if not isinstance(value, dict):
            errors.append(f"{path}: expected an object")
            return None
        return validate(spec, value, path)[0]
    errors.append(f"{path}: unsupported schema type")
    return None


def validate(schema: dict[str, Any], args: dict[str, Any], path: str = "") -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    props, clean = schema.get("properties", {}), {}
    for key, value in args.items():
        if key not in props or value is None:
            continue  # unknown keys are dropped, not fatal
        coerced = _coerce(value, props[key], f"{path}{key}", errors)
        if coerced is not None or props[key].get("type") == "array":
            clean[key] = coerced
    for req in schema.get("required", []):
        if req not in clean:
            errors.append(f"missing required argument '{path}{req}'")
    return clean, errors
