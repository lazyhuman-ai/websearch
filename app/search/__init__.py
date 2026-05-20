"""Python-native multi-engine metasearch core."""

from app.search.agent_tools import web_extract, web_search
from app.search.core import SearchClient
from app.search.tool_schemas import AGENT_TOOL_SCHEMAS, WEB_EXTRACT_TOOL, WEB_SEARCH_TOOL, call_agent_tool
from app.search.types import SearchRequest, SearchResponse, SearchResult, WebDocument
from app.search.url_tools import get_url

__all__ = [
    "AGENT_TOOL_SCHEMAS",
    "SearchClient",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "WEB_EXTRACT_TOOL",
    "WEB_SEARCH_TOOL",
    "call_agent_tool",
    "WebDocument",
    "get_url",
    "web_search",
    "web_extract",
]
