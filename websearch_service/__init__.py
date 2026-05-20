from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = ["WebSearchService", "web_search", "web_search_payload", "web_fetch"]

if TYPE_CHECKING:
    from websearch_service.fetch import web_fetch
    from websearch_service.search import WebSearchService, web_search, web_search_payload


def __getattr__(name: str) -> object:
    if name in {"WebSearchService", "web_search", "web_search_payload"}:
        module = import_module("websearch_service.search")
        return getattr(module, name)
    if name == "web_fetch":
        module = import_module("websearch_service.fetch")
        return getattr(module, name)
    raise AttributeError(f"module 'websearch_service' has no attribute {name!r}")
