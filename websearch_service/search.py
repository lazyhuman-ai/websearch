from __future__ import annotations

import asyncio
import threading
import time
from typing import Literal
from urllib.parse import urlparse

from websearch_service.config import Settings, get_settings
from websearch_service.fetch import get_url
from websearch_service.aggregate import SearchAggregator
from websearch_service.collect import SearchCollector
from websearch_service.engines import build_engine_registry
from websearch_service.planner import RulePlanner
from websearch_service.types import SearchRequest, SearchResponse, SearchResult, WebDocument


Freshness = Literal["any", "day", "week", "month", "year"]

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


class SearchClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.engines = build_engine_registry()
        self.planner = RulePlanner(self.settings)
        self.aggregator = SearchAggregator(self.settings)
        self._ban_lock = threading.Lock()
        self._banned_until: dict[str, float] = {}
        self._engine_successes: dict[str, int] = {}
        self._engine_failures: dict[str, int] = {}
        self._cache: dict[tuple[str, str, str, int, str, int, str, bool, bool], tuple[float, SearchResponse]] = {}

    def search(self, request: SearchRequest) -> SearchResponse:
        prepared = self._prepare_request(request)
        cache_key = (
            prepared.effective_query().lower(),
            prepared.category,
            prepared.language,
            prepared.page,
            prepared.time_range,
            prepared.max_results,
            ",".join(prepared.enabled_engines),
            prepared.resolve_urls,
            prepared.include_url_content,
        )
        cached = self._cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        response = asyncio.run(self._search_async(prepared))
        self._cache[cache_key] = (time.monotonic() + max(1, self.settings.cache_ttl_seconds), response)
        return response

    def read_results(self, results: list[SearchResult], *, limit: int | None = None) -> list[WebDocument]:
        return [self.read_page(item) for item in results[: limit or self.settings.search_read_results]]

    def read_page(self, result: SearchResult) -> WebDocument:
        parsed = result.parsed_url or get_url(result.url, resolve=True, markdown=True, include_content=True, settings=self.settings)
        success = parsed.fetch_succeeded and bool(parsed.content_markdown or parsed.content_text)
        return WebDocument(
            title=parsed.title or result.title,
            url=parsed.final_url or result.url,
            engine=result.engine,
            snippet=result.snippet,
            content_markdown=parsed.content_markdown,
            content_text=parsed.content_text,
            success=success,
            error=parsed.error,
        )

    async def _search_async(self, request: SearchRequest) -> SearchResponse:
        planning_request = request
        decision = self.planner.plan_decision(request, set(self.engines))
        if decision.normalized_query.strip() != request.query.strip() or decision.category != request.category:
            planning_request = SearchRequest(
                query=request.query,
                category=decision.category,  # type: ignore[arg-type]
                language=request.language,
                page=request.page,
                time_range=request.time_range,
                max_results=request.max_results,
                max_engine_requests=request.max_engine_requests,
                enabled_engines=request.enabled_engines,
                site=request.site,
                resolve_urls=request.resolve_urls,
                include_url_content=request.include_url_content,
                planner_query=decision.normalized_query,
            )
        engine_names = decision.engines
        collector = self._build_collector()
        collected = await collector.collect(planning_request, self._prioritize_engines(engine_names))
        hits = collected.hits
        planned_names = collected.planned_names
        failures = collected.failures
        diagnostics = collected.diagnostics
        merged = self.aggregator.merge_and_rank(planning_request, hits)
        if self.aggregator.needs_quality_fallback(planning_request, merged):
            fallback_engines = self.planner.fallback_engines(planning_request, planned_names, set(self.engines))
            if fallback_engines:
                fallback_collected = await collector.collect(planning_request, self._prioritize_engines(fallback_engines))
                hits.extend(fallback_collected.hits)
                planned_names.extend([name for name in fallback_collected.planned_names if name not in planned_names])
                failures.update(fallback_collected.failures)
                diagnostics.update(fallback_collected.diagnostics)
                merged = self.aggregator.merge_and_rank(planning_request, hits)
        results = merged
        if request.resolve_urls:
            results = self.aggregator.resolve_result_urls(results, include_content=request.include_url_content)
        return SearchResponse(
            query=request.query,
            request=planning_request.to_dict(),
            used_engines=planned_names,
            results=results,
            planner={
                "used_llm": decision.used_llm,
                "reason": decision.reason,
                "category": decision.category,
                "normalized_query": decision.normalized_query,
            },
            engine_health=self._engine_health_snapshot(),
            engine_failures=failures,
            engine_diagnostics=diagnostics,
        )

    def _build_collector(self) -> SearchCollector:
        return SearchCollector(
            self.settings,
            self.engines,
            is_banned=self._is_banned,
            record_success=self._record_success,
            record_failure=self._record_failure,
        )

    def _prepare_request(self, request: SearchRequest) -> SearchRequest:
        category = request.category if request.category != "auto" else self.planner.infer_category(request.query)
        return SearchRequest(
            query=request.query.strip(),
            category=category,  # type: ignore[arg-type]
            language=request.language or self.settings.default_language,
            page=max(1, request.page),
            time_range=request.time_range or self.settings.default_time_range,
            max_results=min(max(1, request.max_results), self.settings.max_results_per_query),
            max_engine_requests=max(1, request.max_engine_requests),
            enabled_engines=request.enabled_engines,
            site=request.site,
            resolve_urls=request.resolve_urls,
            include_url_content=request.include_url_content,
        )

    def _is_banned(self, name: str) -> bool:
        with self._ban_lock:
            until = self._banned_until.get(name, 0.0)
            if until <= time.monotonic():
                self._banned_until.pop(name, None)
                return False
            return True

    def _ban(self, name: str, *, reason: str = "") -> None:
        with self._ban_lock:
            duration = self._ban_duration(reason)
            self._banned_until[name] = time.monotonic() + duration

    def _ban_duration(self, reason: str) -> float:
        lowered = reason.lower()
        if "blocked_challenge" in lowered:
            return max(1.0, self.settings.search_challenge_ban_seconds)
        if "http_status=429" in lowered or "rate limit" in lowered:
            return max(1.0, self.settings.search_rate_limit_ban_seconds)
        return max(1.0, self.settings.search_ban_seconds)

    def _record_success(self, name: str, hit_count: int) -> None:
        self._engine_successes[name] = self._engine_successes.get(name, 0) + max(0, hit_count)

    def _record_failure(self, name: str, message: str) -> None:
        self._engine_failures[name] = self._engine_failures.get(name, 0) + 1
        self._ban(name, reason=message)

    def _engine_score(self, name: str) -> tuple[int, int]:
        successes = self._engine_successes.get(name, 0)
        failures = self._engine_failures.get(name, 0)
        return (successes - (failures * 3), successes)

    def _prioritize_engines(self, engine_names: list[str]) -> list[str]:
        indexed = list(enumerate(engine_names))
        indexed.sort(key=lambda item: (self._engine_score(item[1])[0], self._engine_score(item[1])[1], -item[0]), reverse=True)
        return [name for _, name in indexed]

    def _engine_health_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {}
        now = time.monotonic()
        for name in self.engines:
            banned_until = self._banned_until.get(name, 0.0)
            snapshot[name] = {
                "successes": self._engine_successes.get(name, 0),
                "failures": self._engine_failures.get(name, 0),
                "cooldown_active": banned_until > now,
                "cooldown_seconds": max(0.0, round(banned_until - now, 2)),
            }
        return snapshot


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
            {
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet,
                "engine": item.engine,
                "rank": index,
                "published_at": item.published_at,
                "domain": urlparse(item.url).netloc.lower(),
                "score": item.score,
            }
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
