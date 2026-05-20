from __future__ import annotations

from typing import Any

from app.search.agent_tools import web_extract, web_search


WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web across multiple upstream engines and return ranked, agent-friendly results. "
            "Use this when you need candidate URLs, snippets, sources, and planner metadata."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "category": {
                    "type": "string",
                    "enum": ["auto", "general", "news", "reference", "academic", "code"],
                    "description": "Optional search category hint.",
                },
                "language": {"type": "string", "description": "Language hint such as en-US or zh-CN."},
                "site": {"type": "string", "description": "Optional site restriction such as docs.python.org."},
                "time_range": {
                    "type": "string",
                    "enum": ["any", "day", "week", "month", "year"],
                    "description": "Optional freshness constraint.",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "How many results to request per upstream search request.",
                },
                "max_engine_requests": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Maximum number of paginated requests to send to each engine.",
                },
                "enabled_engines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional explicit engine allowlist.",
                },
                "engine_config_path": {
                    "type": "string",
                    "description": "Optional path to a YAML engine configuration file.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


WEB_EXTRACT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_extract",
        "description": (
            "Resolve URLs and extract readable content for agent use. "
            "Use this after web_search when the agent needs page text rather than just URLs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of URLs to resolve and extract.",
                },
                "include_content": {
                    "type": "boolean",
                    "description": "Whether to include extracted readable content.",
                },
                "markdown": {
                    "type": "boolean",
                    "description": "Whether markdown-formatted output is preferred when available.",
                },
                "resolve": {
                    "type": "boolean",
                    "description": "Whether to follow redirects and normalize final URLs.",
                },
                "max_urls": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Maximum number of URLs to extract in one call.",
                },
            },
            "required": ["urls"],
            "additionalProperties": False,
        },
    },
}


AGENT_TOOL_SCHEMAS: list[dict[str, Any]] = [WEB_SEARCH_TOOL, WEB_EXTRACT_TOOL]


def call_agent_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call by name using a runtime-friendly interface."""

    if name == "web_search":
        return web_search(
            query=str(arguments["query"]),
            category=str(arguments.get("category", "auto")),  # type: ignore[arg-type]
            language=str(arguments.get("language", "en-US")),
            site=str(arguments["site"]) if arguments.get("site") is not None else None,
            time_range=str(arguments.get("time_range", "any")),  # type: ignore[arg-type]
            max_results=int(arguments.get("max_results", 5)),
            max_engine_requests=int(arguments.get("max_engine_requests", 1)),
            enabled_engines=[str(item) for item in arguments.get("enabled_engines", [])] if isinstance(arguments.get("enabled_engines"), list) else None,
            engine_config_path=str(arguments["engine_config_path"]) if arguments.get("engine_config_path") is not None else None,
        )
    if name == "web_extract":
        urls = [str(item) for item in arguments.get("urls", [])] if isinstance(arguments.get("urls"), list) else []
        return web_extract(
            urls=urls,
            include_content=bool(arguments.get("include_content", True)),
            markdown=bool(arguments.get("markdown", True)),
            resolve=bool(arguments.get("resolve", True)),
            max_urls=int(arguments.get("max_urls", 3)),
        )
    raise ValueError(f"Unsupported tool name: {name}")
