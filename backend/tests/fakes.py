"""A stand-in for the Claude API.

Validates every scripted payload against the REAL tool schema. Without that,
fakes slowly drift into a response shape the API would never produce and the
tests stop meaning anything.
"""

from typing import Any

from app.services import llm


class FakeLLM:
    """Scripted responses, keyed by tool name.

    A scripted entry may be an Exception, which is raised - that is how the
    partial-failure and refusal paths get exercised.
    """

    def __init__(self, script: dict[str, Any] | None = None):
        self.script = script or {}
        self.calls: list[dict[str, Any]] = []

    def call_tool(self, *, system, content, tool, max_tokens=8000, effort="medium"):
        self.calls.append(
            {
                "tool": tool["name"],
                "effort": effort,
                "content_types": [b["type"] for b in content],
                "first_block_cached": "cache_control" in content[0],
                "field_keys": tool["input_schema"]["properties"]
                .get("fields", {})
                .get("items", {})
                .get("properties", {})
                .get("field_key", {})
                .get("enum"),
                "system": system,
            }
        )
        entry = self.script.get(tool["name"])
        if isinstance(entry, list):
            entry = entry.pop(0) if entry else {}
        if isinstance(entry, Exception):
            raise entry
        data = entry if entry is not None else {}
        _assert_matches_schema(data, tool)
        return llm.LLMResult(data=data, input_tokens=100, output_tokens=50)


def _assert_matches_schema(data: dict, tool: dict) -> None:
    """Minimal structural check against the tool the code actually sent."""
    props = tool["input_schema"]["properties"]
    if tool["name"] == llm.CLASSIFY_TOOL_NAME:
        allowed = props["type_key"]["enum"]
        assert data.get("type_key") in allowed, f"{data.get('type_key')!r} not in enum"
        return
    if tool["name"] == llm.NAVIGATE_TOOL_NAME:
        for key in ("content_first_page", "content_last_page", "confidence", "reason"):
            assert key in data, f"missing {key}"
        return
    allowed = props["fields"]["items"]["properties"]["field_key"]["enum"]
    for item in data.get("fields", []):
        assert item["field_key"] in allowed, f"{item['field_key']!r} not in enum"
        for key in ("value", "confidence", "page", "snippet"):
            assert key in item, f"missing {key}"


def classified(type_key: str, confidence: float = 0.95) -> dict:
    return {"type_key": type_key, "confidence": confidence, "reason": "fake"}


def extracted(*fields) -> dict:
    """`extracted(("court_name", "השלום", 0.9, 1, "בית משפט השלום"))`"""
    return {
        "fields": [
            {"field_key": k, "value": v, "confidence": c, "page": p, "snippet": s}
            for k, v, c, p, s in fields
        ]
    }
