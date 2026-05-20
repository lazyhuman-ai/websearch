from __future__ import annotations

from websearch_service.app import web_fetch as service_web_fetch
from websearch_service.app import web_search as service_web_search


def web_search(
    query: str,
    count: int | None = None,
    language: str = "en-US",
    freshness: str = "any",
    providers: list[str] | None = None,
) -> list[dict[str, object]]:
    """Search wrapper optimized for agent tool calls."""

    return service_web_search(
        query=query,
        count=count,
        language=language,
        freshness=freshness,  # type: ignore[arg-type]
        providers=providers,
    )


def web_fetch(url: str) -> dict[str, object]:
    """Fetch and clean a single web page for agent tool calls."""

    return service_web_fetch(url)


def web_extract(
    urls: list[str],
    *,
    max_urls: int = 3,
) -> dict[str, object]:
    """Backward-compatible batch wrapper around `web_fetch`."""

    limited_urls = [item.strip() for item in urls if item and item.strip()][: max(1, max_urls)]
    return {
        "url_count": len(limited_urls),
        "documents": [service_web_fetch(url) for url in limited_urls],
    }
