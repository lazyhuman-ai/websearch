from __future__ import annotations

from app.search.core import SearchClient
from app.search.types import ParsedUrlResult, SearchCategory, SearchRequest, TimeRange
from app.search.url_tools import get_url


def web_search(
    query: str,
    *,
    category: SearchCategory = "auto",
    language: str = "en-US",
    site: str | None = None,
    time_range: TimeRange = "any",
    max_results: int = 5,
    max_engine_requests: int = 1,
    enabled_engines: list[str] | None = None,
    engine_config_path: str | None = None,
    client: SearchClient | None = None,
) -> dict[str, object]:
    """Search the web and return agent-friendly structured results."""

    active_client = client or SearchClient()
    request = SearchRequest(
        query=query,
        category=category,
        language=language,
        site=site,
        time_range=time_range,
        max_results=max_results,
        max_engine_requests=max_engine_requests,
        enabled_engines=list(enabled_engines or []),
        resolve_urls=False,
        include_url_content=False,
        engine_config_path=engine_config_path,
    )
    response = active_client.search(request)
    return {
        "query": response.query,
        "request": response.request,
        "used_engines": response.used_engines,
        "results": [
            {
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet,
                "engine": item.engine,
                "engines": item.engines,
                "source_type": item.source_type,
                "published_at": item.published_at,
                "score": item.score,
            }
            for item in response.results
        ],
        "planner": response.planner,
        "engine_health": response.engine_health,
        "engine_failures": response.engine_failures,
    }


def web_extract(
    urls: list[str],
    *,
    include_content: bool = True,
    markdown: bool = True,
    resolve: bool = True,
    max_urls: int = 3,
) -> dict[str, object]:
    """Resolve URLs and extract readable content for agent use."""

    limited_urls = [item.strip() for item in urls if item and item.strip()][: max(1, max_urls)]
    documents: list[dict[str, object]] = []
    for url in limited_urls:
        parsed: ParsedUrlResult = get_url(
            url,
            resolve=resolve,
            markdown=markdown,
            include_content=include_content,
        )
        documents.append(
            {
                "input_url": parsed.input_url,
                "resolved_url": parsed.resolved_url,
                "final_url": parsed.final_url,
                "title": parsed.title,
                "content_markdown": parsed.content_markdown,
                "content_text": parsed.content_text,
                "content_excerpt": parsed.content_excerpt,
                "content_type": parsed.content_type,
                "fetch_succeeded": parsed.fetch_succeeded,
                "error": parsed.error,
            }
        )
    return {
        "url_count": len(limited_urls),
        "documents": documents,
    }
