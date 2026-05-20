from __future__ import annotations

from urllib.parse import urlparse

from websearch_service.config import Settings, get_settings
from websearch_service.fetch import fetch_url
from websearch_service.search.core import SearchClient
from websearch_service.search.types import SearchRequest, SearchResponse
from websearch_service.schemas import Freshness, SearchResultItem

PROVIDER_TO_ENGINE = {
    "google": "google_web",
    "bing": "bing_web",
    "brave": "brave_web",
    "duckduckgo": "duckduckgo_lite",
    "duckduckgo_lite": "duckduckgo_lite",
    "google_web": "google_web",
    "bing_web": "bing_web",
    "brave_web": "brave_web",
    "google_news_rss": "google_news_rss",
    "wikipedia": "wikipedia",
    "arxiv": "arxiv",
    "stackoverflow": "stackoverflow",
    "github": "github",
}

ENGINE_TO_PROVIDER = {
    "google_web": "google",
    "bing_web": "bing",
    "brave_web": "brave",
    "duckduckgo_lite": "duckduckgo",
    "google_news_rss": "google_news",
    "wikipedia": "wikipedia",
    "arxiv": "arxiv",
    "stackoverflow": "stackoverflow",
    "github": "github",
}


class WebSearchService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = SearchClient(self.settings)

    def web_search(
        self,
        query: str,
        count: int | None = None,
        language: str = "en-US",
        freshness: Freshness = "any",
        providers: list[str] | None = None,
    ) -> list[dict[str, object]]:
        payload = self.search_payload(
            query=query,
            count=count,
            language=language,
            freshness=freshness,
            providers=providers,
        )
        return payload["results"]  # type: ignore[return-value]

    def search_payload(
        self,
        query: str,
        count: int | None = None,
        language: str = "en-US",
        freshness: Freshness = "any",
        providers: list[str] | None = None,
    ) -> dict[str, object]:
        explicit_engines = _normalize_provider_names(providers)
        requested_count = self.settings.max_results_per_query if count is None or count <= 0 else count
        request = SearchRequest(
            query=query.strip(),
            category="auto",
            language=language or self.settings.default_language,
            time_range=freshness,
            max_results=min(max(1, requested_count), self.settings.max_results_per_query),
            max_engine_requests=1,
            enabled_engines=explicit_engines,
            resolve_urls=False,
            include_url_content=False,
        )
        response = self.client.search(request)
        results = [
            SearchResultItem(
                title=item.title,
                url=item.url,
                snippet=item.snippet,
                engine=item.engine,
                rank=index,
                published_at=item.published_at,
                domain=urlparse(item.url).netloc.lower(),
                score=item.score,
            ).to_dict()
            for index, item in enumerate(response.results, start=1)
        ]
        return _build_search_payload(
            response=response,
            query=query,
            count=count,
            language=language,
            freshness=freshness,
            requested_providers=list(providers or []),
            results=results,
        )

    def web_fetch(self, url: str) -> dict[str, object]:
        return fetch_url(url, settings=self.settings).to_dict()


_default_service = WebSearchService()


def web_search(
    query: str,
    count: int | None = None,
    language: str = "en-US",
    freshness: Freshness = "any",
    providers: list[str] | None = None,
) -> list[dict[str, object]]:
    return _default_service.web_search(
        query=query,
        count=count,
        language=language,
        freshness=freshness,
        providers=providers,
    )


def web_search_payload(
    query: str,
    count: int | None = None,
    language: str = "en-US",
    freshness: Freshness = "any",
    providers: list[str] | None = None,
) -> dict[str, object]:
    return _default_service.search_payload(
        query=query,
        count=count,
        language=language,
        freshness=freshness,
        providers=providers,
    )


def web_fetch(url: str) -> dict[str, object]:
    return _default_service.web_fetch(url)


def _normalize_provider_names(providers: list[str] | None) -> list[str]:
    if not providers:
        return []
    normalized: list[str] = []
    for name in providers:
        engine_name = PROVIDER_TO_ENGINE.get(name.strip().lower())
        if engine_name and engine_name not in normalized:
            normalized.append(engine_name)
    return normalized


def _display_provider_names(engine_names: list[str]) -> list[str]:
    displayed: list[str] = []
    for name in engine_names:
        provider_name = ENGINE_TO_PROVIDER.get(name, name)
        if provider_name not in displayed:
            displayed.append(provider_name)
    return displayed


def _build_search_payload(
    *,
    response: SearchResponse,
    query: str,
    count: int | None,
    language: str,
    freshness: Freshness,
    requested_providers: list[str],
    results: list[dict[str, object]],
) -> dict[str, object]:
    failed_engines = list(response.engine_failures)
    return {
        "query": query,
        "count": count,
        "language": language,
        "freshness": freshness,
        "requested_providers": requested_providers,
        "providers": _display_provider_names(response.used_engines),
        "used_engines": response.used_engines,
        "failed_providers": _display_provider_names(failed_engines),
        "failed_engines": failed_engines,
        "engine_failures": response.engine_failures,
        "engine_diagnostics": response.engine_diagnostics,
        "planner": response.planner,
        "engine_health": response.engine_health,
        "results": results,
    }
