from __future__ import annotations

from typing import Any

from websearch_service.search.agent_tools import web_extract, web_fetch, web_search


WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web across multiple providers and return normalized, agent-friendly results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 20,
                    "description": "Per-engine fetch count. Use 0 or omit to return the full aggregated ranked list.",
                },
                "language": {"type": "string", "description": "Language hint such as en-US or zh-CN."},
                "freshness": {
                    "type": "string",
                    "enum": ["any", "day", "week", "month", "year"],
                    "description": "Optional freshness constraint.",
                },
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional explicit provider allowlist such as google or brave.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


WEB_FETCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": (
            "Fetch a page and return cleaned text, title, excerpt, and metadata for agent use."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The page URL to fetch and clean."},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}


WEB_EXTRACT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_extract",
        "description": "Backward-compatible batch wrapper around web_fetch.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of URLs to fetch.",
                },
                "max_urls": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Maximum number of URLs to fetch in one call.",
                },
            },
            "required": ["urls"],
            "additionalProperties": False,
        },
    },
}


AGENT_TOOL_SCHEMAS: list[dict[str, Any]] = [WEB_SEARCH_TOOL, WEB_FETCH_TOOL, WEB_EXTRACT_TOOL]


def call_agent_tool(name: str, arguments: dict[str, Any]) -> object:
    """Dispatch a tool call by name using a runtime-friendly interface."""

    if name == "web_search":
        return web_search(
            query=str(arguments["query"]),
            count=int(arguments["count"]) if arguments.get("count") is not None else None,
            language=str(arguments.get("language", "en-US")),
            freshness=str(arguments.get("freshness", "any")),  # type: ignore[arg-type]
            providers=[str(item) for item in arguments.get("providers", [])] if isinstance(arguments.get("providers"), list) else None,
        )
    if name == "web_fetch":
        return web_fetch(url=str(arguments["url"]))
    if name == "web_extract":
        urls = [str(item) for item in arguments.get("urls", [])] if isinstance(arguments.get("urls"), list) else []
        return web_extract(
            urls=urls,
            max_urls=int(arguments.get("max_urls", 3)),
        )
    raise ValueError(f"Unsupported tool name: {name}")
