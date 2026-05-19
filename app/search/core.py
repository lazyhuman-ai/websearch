from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterable
from urllib.parse import urlparse

from app.config import Settings, get_settings
from app.search.engines import build_engine_registry
from app.search.normalize import canonical_result_key, looks_low_quality, normalize_url
from app.search.planner import RulePlanner
from app.search.privacy import build_async_client, choose_user_agent
from app.search.rank import has_meaningful_overlap, score_hit
from app.search.types import ParsedUrlResult, RawSearchHit, SearchRequest, SearchResponse, SearchResult, WebDocument
from app.search.url_tools import get_url


class SearchClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.engines = build_engine_registry()
        self.planner = RulePlanner(self.settings)
        self._ban_lock = threading.Lock()
        self._banned_until: dict[str, float] = {}
        self._engine_successes: dict[str, int] = {}
        self._engine_failures: dict[str, int] = {}
        self._cache: dict[tuple[str, str, str, int, str, int, str, bool, bool, str], tuple[float, SearchResponse]] = {}

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
            prepared.engine_config_path or "",
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
                engine_config_path=request.engine_config_path,
                planner_query=decision.normalized_query,
            )
        engine_names = decision.engines
        hits, planned_names, failures = await self._collect_hits(planning_request, self._prioritize_engines(engine_names))
        merged = self._merge_hits(planning_request, hits)
        if self._needs_quality_fallback(planning_request, merged):
            fallback_engines = self.planner.fallback_engines(planning_request, planned_names, set(self.engines))
            if fallback_engines:
                fallback_hits, fallback_names, fallback_failures = await self._collect_hits(planning_request, self._prioritize_engines(fallback_engines))
                hits.extend(fallback_hits)
                planned_names.extend([name for name in fallback_names if name not in planned_names])
                failures.update(fallback_failures)
                merged = self._merge_hits(planning_request, hits)
        results = merged
        if request.resolve_urls:
            results = self._resolve_result_urls(results, include_content=request.include_url_content)
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
        )

    async def _collect_hits(self, request: SearchRequest, engine_names: list[str]) -> tuple[list[RawSearchHit], list[str], dict[str, str]]:
        user_agent = choose_user_agent(self.settings.user_agent, self.settings.search_user_agent_rotation)
        failures: dict[str, str] = {}
        async with build_async_client(
            timeout_seconds=self.settings.search_engine_timeout_seconds,
            follow_redirects=True,
            user_agent=user_agent,
            accept_language=request.language,
        ) as client:
            tasks = []
            planned_names = []
            for name in engine_names:
                if self._is_banned(name):
                    continue
                engine = self.engines.get(name)
                if engine is None or not engine.supports(request):
                    continue
                tasks.append(self._run_engine(engine, client, request))
                planned_names.append(name)
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=self.settings.search_total_timeout_seconds) if tasks else []
        hits: list[RawSearchHit] = []
        for name, result in zip(planned_names, results):
            if isinstance(result, Exception):
                failures[name] = str(result)
                self._record_failure(name, str(result))
                continue
            self._record_success(name, len(result))
            hits.extend(result)
        return hits, planned_names, failures

    async def _run_engine(self, engine, client, request: SearchRequest) -> list[RawSearchHit]:
        raw_hits = await engine.search(client, request)
        hits: list[RawSearchHit] = []
        for hit in raw_hits:
            if not hit.url or not hit.title or looks_low_quality(hit.title, hit.url):
                continue
            if not has_meaningful_overlap(request.effective_query(), hit.title, hit.snippet):
                continue
            hit.canonical_url = normalize_url(hit.url, strip_trackers=self.settings.search_strip_trackers)
            if request.site and not self._matches_site(hit.canonical_url or hit.url, request.site):
                continue
            _, title_key = canonical_result_key(hit.canonical_url or hit.url, hit.title)
            hit.title_signature = title_key
            hits.append(hit)
        return hits

    def _merge_hits(self, request: SearchRequest, hits: Iterable[RawSearchHit]) -> list[SearchResult]:
        merged: dict[str, RawSearchHit] = {}
        title_fallbacks: dict[str, str] = {}
        for hit in hits:
            key, title_key = canonical_result_key(hit.canonical_url or hit.url, hit.title)
            existing_key = title_fallbacks.get(title_key, key) if key not in merged else key
            current = merged.get(existing_key)
            if current is None:
                hit.canonical_url = key
                hit.title_signature = title_key
                merged[existing_key] = hit
                title_fallbacks[title_key] = existing_key
                continue
            current.title = hit.title if len(hit.title) > len(current.title) else current.title
            current.snippet = hit.snippet if len(hit.snippet) > len(current.snippet) else current.snippet
            current.engines = sorted(set(current.engines + hit.engines + ([hit.engine] if hit.engine else [])))
            current.engine = ", ".join(current.engines)
            if current.published_at is None or (hit.published_at and current.published_at and hit.published_at > current.published_at):
                current.published_at = hit.published_at
        ranked = list(merged.values())
        for item in ranked:
            item.engine = ", ".join(item.engines)
            item.score = score_hit(request.effective_query(), item, category=request.category)
            item.snippet = item.snippet or item.title
        ranked.sort(key=lambda item: item.score, reverse=True)
        return [
            SearchResult(
                title=item.title,
                url=item.canonical_url or item.url,
                snippet=item.snippet,
                engine=item.engine,
                engines=item.engines,
                source_type=item.source_type or "web",
                published_at=item.published_at.isoformat() if item.published_at else None,
                score=item.score,
            )
            for item in ranked
        ]

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
            engine_config_path=request.engine_config_path,
        )

    def _resolve_result_urls(self, results: list[SearchResult], *, include_content: bool) -> list[SearchResult]:
        cleaned: list[SearchResult] = []
        for item in results:
            parsed_url = get_url(
                item.url,
                resolve=True,
                markdown=True,
                include_content=include_content,
                settings=self.settings,
            )
            if parsed_url.error == "blocked_interstitial" or parsed_url.domain.lower() == "consent.google.com":
                item.parsed_url = None
                cleaned.append(item)
                continue
            item.parsed_url = parsed_url
            if item.parsed_url.content_excerpt and (not item.snippet or item.snippet == item.title):
                item.snippet = item.parsed_url.content_excerpt
            if self._should_keep_result(item, include_content=include_content):
                cleaned.append(item)
        return cleaned

    def _should_keep_result(self, item: SearchResult, *, include_content: bool) -> bool:
        parsed = item.parsed_url
        domain = urlparse(item.url).netloc.lower()
        title = (item.title or "").strip().lower()
        snippet = (item.snippet or "").strip().lower()
        if item.source_type == "news" and ("youtube.com" in domain or "youtu.be" in domain):
            return False
        if item.source_type == "news" and not any(token in domain for token in ("news", "nasdaq", "reuters", "apnews", "cnbc", "bloomberg", "wsj", "ft.com", "finance")):
            if "youtube" in title or "youtube" in snippet:
                return False
        if parsed is None:
            return True
        parsed_title = (parsed.title or "").strip().lower()
        parsed_excerpt = (parsed.content_excerpt or "").strip().lower()
        if parsed_title == "before you continue" or parsed_title.startswith("before you continue to google"):
            return False
        if "youtube" in domain and parsed_excerpt.startswith("about press copyright contact us creators"):
            return False
        return True

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

    def _matches_site(self, url: str, site: str) -> bool:
        host = urlparse(url).netloc.lower()
        normalized = site.lower().strip()
        return host == normalized or host.endswith(f".{normalized}")

    def _needs_quality_fallback(self, request: SearchRequest, results: list[SearchResult]) -> bool:
        if not results:
            return True
        if request.site:
            return len(results) < min(2, request.max_results)
        return max(item.score for item in results) < 0.18

    def _ban_duration(self, reason: str) -> float:
        lowered = reason.lower()
        if "blocked_challenge" in lowered:
            return max(1.0, self.settings.search_challenge_ban_seconds)
        if "http_status=429" in lowered or "rate limit" in lowered:
            return max(1.0, self.settings.search_rate_limit_ban_seconds)
        return max(1.0, self.settings.search_ban_seconds)

    def _record_success(self, name: str, hit_count: int) -> None:
        self._engine_successes[name] = self._engine_successes.get(name, 0) + max(1, hit_count)

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
