"""Python-native multi-engine metasearch core."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "AGENT_TOOL_SCHEMAS",
    "SearchClient",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "WEB_EXTRACT_TOOL",
    "WEB_FETCH_TOOL",
    "WEB_SEARCH_TOOL",
    "WebDocument",
    "call_agent_tool",
    "get_url",
    "web_extract",
    "web_fetch",
    "web_search",
]

if TYPE_CHECKING:
    from websearch_service.search.agent_tools import web_extract, web_fetch, web_search
    from websearch_service.search.core import SearchClient
    from websearch_service.search.tool_schemas import AGENT_TOOL_SCHEMAS, WEB_EXTRACT_TOOL, WEB_FETCH_TOOL, WEB_SEARCH_TOOL, call_agent_tool
    from websearch_service.search.types import SearchRequest, SearchResponse, SearchResult, WebDocument
    from websearch_service.search.url_tools import get_url


def __getattr__(name: str) -> object:
    if name in {"web_extract", "web_fetch", "web_search"}:
        module = import_module("websearch_service.search.agent_tools")
        return getattr(module, name)
    if name in {"AGENT_TOOL_SCHEMAS", "WEB_EXTRACT_TOOL", "WEB_FETCH_TOOL", "WEB_SEARCH_TOOL", "call_agent_tool"}:
        module = import_module("websearch_service.search.tool_schemas")
        return getattr(module, name)
    if name == "SearchClient":
        return getattr(import_module("websearch_service.search.core"), name)
    if name in {"SearchRequest", "SearchResponse", "SearchResult", "WebDocument"}:
        module = import_module("websearch_service.search.types")
        return getattr(module, name)
    if name == "get_url":
        return getattr(import_module("websearch_service.search.url_tools"), name)
    raise AttributeError(f"module 'websearch_service.search' has no attribute {name!r}")
