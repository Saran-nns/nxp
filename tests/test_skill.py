"""Tests for skill schema extraction from Python type hints."""

from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from nxp.skill import _extract_param_schema, _type_to_schema


# ─── Type to Schema ──────────────────────────────────────────────────────────────


def test_primitive_types():
    assert _type_to_schema(str) == {"type": "string"}
    assert _type_to_schema(int) == {"type": "integer"}
    assert _type_to_schema(float) == {"type": "number"}
    assert _type_to_schema(bool) == {"type": "boolean"}


def test_list_type():
    schema = _type_to_schema(List[str])
    assert schema["type"] == "array"
    assert schema["items"] == {"type": "string"}


def test_list_of_ints():
    schema = _type_to_schema(List[int])
    assert schema["type"] == "array"
    assert schema["items"] == {"type": "integer"}


def test_optional_type():
    schema = _type_to_schema(Optional[str])
    assert schema["type"] == "string"
    assert schema.get("nullable") is True


def test_optional_int():
    schema = _type_to_schema(Optional[int])
    assert schema["type"] == "integer"
    assert schema.get("nullable") is True


def test_dict_type():
    schema = _type_to_schema(Dict[str, str])
    assert schema["type"] == "object"


# ─── Parameter Schema Extraction ─────────────────────────────────────────────────


def test_required_params():
    def fn(query: str, limit: int) -> str:
        return ""

    schema = _extract_param_schema(fn)
    assert "query" in schema["required"]
    assert "limit" in schema["required"]


def test_optional_params_not_required():
    def fn(query: str, limit: int = 10) -> str:
        return ""

    schema = _extract_param_schema(fn)
    assert "query" in schema["required"]
    assert "limit" not in schema.get("required", [])
    assert schema["properties"]["limit"]["default"] == 10


def test_no_params():
    def fn() -> str:
        return "hello"

    schema = _extract_param_schema(fn)
    assert schema["properties"] == {}
    assert schema.get("required", []) == []


def test_return_excluded():
    """Return annotation should NOT appear in parameter schema."""

    def fn(x: int) -> str:
        return str(x)

    schema = _extract_param_schema(fn)
    assert "return" not in schema["properties"]


def test_mixed_params():
    def search(
        query: str,
        limit: int = 5,
        tags: Optional[List[str]] = None,
        verbose: bool = False,
    ) -> str:
        return ""

    schema = _extract_param_schema(search)
    props = schema["properties"]
    required = schema.get("required", [])

    assert "query" in required
    assert "limit" not in required
    assert "tags" not in required
    assert "verbose" not in required

    assert props["limit"]["default"] == 5
    assert props["verbose"]["default"] is False
    assert props["tags"]["nullable"] is True


def test_self_excluded():
    """'self' parameter should not appear in the schema."""

    class MyClass:
        def method(self, x: int) -> int:
            return x

    schema = _extract_param_schema(MyClass.method)
    assert "self" not in schema["properties"]
