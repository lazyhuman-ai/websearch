"""Python-native multi-engine metasearch core."""

from app.search.core import SearchClient
from app.search.types import SearchRequest, SearchResponse, SearchResult, WebDocument

__all__ = ["SearchClient", "SearchRequest", "SearchResponse", "SearchResult", "WebDocument"]
