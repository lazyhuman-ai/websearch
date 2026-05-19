"""Python-native multi-engine metasearch core."""

from app.search.core import SearchClient
from app.search.types import SearchRequest, SearchResponse, SearchResult, WebDocument
from app.search.url_tools import get_url

__all__ = ["SearchClient", "SearchRequest", "SearchResponse", "SearchResult", "WebDocument", "get_url"]
