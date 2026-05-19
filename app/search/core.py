from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections.abc import Iterable
from urllib.parse import urlparse

import httpx
import trafilatura

from app.config import Settings, get_settings
from app.search.adapters import build_adapter_registry
from app.search.normalize import canonical_result_key, looks_low_quality, normalize_url
from app.search.privacy import build_async_client, choose_user_agent
from app.search.rank import score_hit
from app.search.types import RawSearchHit, SearchCategory, SearchRequest, SearchResponse, SearchResult, WebDocument


logger = logging.getLogger(__name__)
NEWS_HINT_RE = re.compile(r"\b(latest|recent|today|news|headline|breaking)\b", re.I)
ACADEMIC_HINT_RE = re.compile(r"\b(paper|survey|benchmark|arxiv|research)\b", re.I)
CODE_HINT_RE = re.compile(r"\b(github|repo|repository|issue|sdk|library|debug|bug)\b", re.I)
REFERENCE_HINT_RE = re.compile(r"\b(who is|what is|history|biography|definition|wiki)\b", re.I)
CANONICAL_URL_RE = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.I)
OG_URL_RE = re.compile(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', re.I)
META_REFRESH_RE = re.compile(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^;]+;\s*url=([^"\']+)["\']', re.I)
MULTI_BLANK_RE = re.compile(r"\n{3,}")


class SearchClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.adapters = build_adapter_registry()
        self._ban_lock = threading.Lock()
        self._banned_until: dict[str, float] = {}
        self._cache: dict[tuple[str, str, str, int, str], tuple[float, SearchResponse]] = {}
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    def search(self, request: SearchRequest) -> SearchResponse:
        prepared = self._prepare_request(request)
        cache_key = (
            prepared.effective_query().lower(),
            prepared.category,
            prepared.language,
            prepared.page,
            ",".join(prepared.enabled_engines),
        )
        cached = self._cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        self._respect_request_interval()
        response = asyncio.run(self._search_async(prepared))
        self._cache[cache_key] = (time.monotonic() + max(1, self.settings.cache_ttl_seconds), response)
        return response

    def read_results(self, results: list[SearchResult], *, limit: int | None = None) -> list[WebDocument]:
        return [self.read_page(item) for item in results[: limit or self.settings.search_read_results]]

    def read_page(self, result: SearchResult) -> WebDocument:
        try:
            final_url = result.url
            with httpx.Client(timeout=self.settings.request_timeout_seconds, follow_redirects=True, headers={"User-Agent": self.settings.user_agent}) as client:
                response = client.get(result.url)
                response.raise_for_status()
                final_url = str(response.url)
                html = response.text
                resolved = self._resolve_article_url(result.url, final_url, html)
                if resolved != final_url:
                    response = client.get(resolved)
                    response.raise_for_status()
                    final_url = str(response.url)
                    html = response.text
        except httpx.HTTPError as exc:
            return WebDocument(title=result.title, url=result.url, engine=result.engine, snippet=result.snippet, success=False, error=f"fetch_error: {exc}")

        extracted = trafilatura.extract(
            html,
            url=final_url,
            include_links=False,
            include_images=False,
            output_format="markdown",
            favor_recall=True,
            deduplicate=True,
        )
        if not extracted:
            return WebDocument(title=result.title, url=final_url, engine=result.engine, snippet=result.snippet, success=False, error="extract_error: empty_content")
        return WebDocument(
            title=result.title,
            url=final_url,
            engine=result.engine,
            snippet=result.snippet,
            content=self._clean_text(extracted),
            success=True,
        )

    async def _search_async(self, request: SearchRequest) -> SearchResponse:
        engine_names = self._plan_engines(request)
        hits, planned_names, failures = await self._collect_hits(request, engine_names)
        merged = self._merge_hits(request, hits)
        if self._needs_quality_fallback(request, merged):
            fallback_engines = self._fallback_engines(request, planned_names)
            if fallback_engines:
                fallback_hits, fallback_names, fallback_failures = await self._collect_hits(request, fallback_engines)
                hits.extend(fallback_hits)
                planned_names.extend([name for name in fallback_names if name not in planned_names])
                failures.update(fallback_failures)
                merged = self._merge_hits(request, hits)
        return SearchResponse(
            query=request.query,
            request=request.to_dict(),
            used_engines=planned_names,
            results=merged[: request.max_results],
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
                    failures[name] = "banned"
                    continue
                adapter = self.adapters.get(name)
                if adapter is None or not adapter.supports(request):
                    failures[name] = "unsupported"
                    continue
                tasks.append(self._run_adapter(adapter, client, request))
                planned_names.append(name)
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=self.settings.search_total_timeout_seconds) if tasks else []
        hits: list[RawSearchHit] = []
        for name, result in zip(planned_names, results):
            if isinstance(result, Exception):
                failures[name] = str(result)
                continue
            hits.extend(result)
        return hits, planned_names, failures

    async def _run_adapter(self, adapter, client: httpx.AsyncClient, request: SearchRequest) -> list[RawSearchHit]:
        try:
            raw_hits = await adapter.search(client, request)
        except Exception:
            self._ban(adapter.name)
            raise
        hits: list[RawSearchHit] = []
        for hit in raw_hits:
            if not hit.url or not hit.title or looks_low_quality(hit.title, hit.url):
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
        ranked.sort(key=lambda item: item.score, reverse=True)
        return [
            SearchResult(
                title=item.title,
                url=item.canonical_url or item.url,
                snippet=item.snippet,
                engine=item.engine,
                engines=item.engines,
                published_at=item.published_at.isoformat() if item.published_at else None,
                score=item.score,
            )
            for item in ranked
        ]

    def _prepare_request(self, request: SearchRequest) -> SearchRequest:
        category = request.category
        if category == "auto":
            lowered = request.query.lower()
            if NEWS_HINT_RE.search(lowered):
                category = "news"
            elif ACADEMIC_HINT_RE.search(lowered):
                category = "academic"
            elif CODE_HINT_RE.search(lowered):
                category = "code"
            elif REFERENCE_HINT_RE.search(lowered):
                category = "reference"
            else:
                category = self.settings.default_category  # type: ignore[assignment]
        return SearchRequest(
            query=request.query.strip(),
            category=category,
            language=request.language or self.settings.default_language,
            page=max(1, request.page),
            time_range=request.time_range or self.settings.default_time_range,
            max_results=min(max(1, request.max_results), self.settings.max_results_per_query),
            enabled_engines=request.enabled_engines,
            site=request.site,
        )

    def _plan_engines(self, request: SearchRequest) -> list[str]:
        if request.enabled_engines:
            return [name for name in request.enabled_engines if name in self.adapters]
        if request.site:
            base = ["google_web", "bing_web", "duckduckgo_lite"]
            return [name for name in base if name in self.adapters]
        if request.category == "news":
            return self.settings.news_engines
        if request.category == "reference":
            return self.settings.reference_engines
        if request.category == "academic":
            return self.settings.academic_engines
        if request.category == "code":
            return self.settings.code_engines
        engines = list(self.settings.general_engines)
        lowered = request.query.lower()
        if REFERENCE_HINT_RE.search(lowered) or lowered.startswith("what is ") or lowered.startswith("who is "):
            if "wikipedia" not in engines:
                engines.append("wikipedia")
        return engines

    def _respect_request_interval(self) -> None:
        with self._request_lock:
            now = time.monotonic()
            wait_seconds = self.settings.request_interval_seconds - (now - self._last_request_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_request_at = time.monotonic()

    def _is_banned(self, name: str) -> bool:
        with self._ban_lock:
            until = self._banned_until.get(name, 0.0)
            if until <= time.monotonic():
                self._banned_until.pop(name, None)
                return False
            return True

    def _ban(self, name: str) -> None:
        with self._ban_lock:
            self._banned_until[name] = time.monotonic() + max(1.0, self.settings.search_ban_seconds)

    def _resolve_article_url(self, original_url: str, fetched_url: str, html: str) -> str:
        original_host = urlparse(original_url).netloc.lower()
        fetched_host = urlparse(fetched_url).netloc.lower()
        if original_host != "news.google.com" and fetched_host != "news.google.com":
            return fetched_url
        for pattern in (CANONICAL_URL_RE, OG_URL_RE, META_REFRESH_RE):
            match = pattern.search(html or "")
            if match:
                candidate = match.group(1).strip()
                if candidate.startswith("http") and "news.google.com" not in urlparse(candidate).netloc.lower():
                    return candidate
        return fetched_url

    def _clean_text(self, text: str) -> str:
        text = MULTI_BLANK_RE.sub("\n\n", text.strip())
        if len(text) <= self.settings.max_document_chars:
            return text
        return text[: self.settings.max_document_chars].rstrip() + "\n\n[TRUNCATED]"

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

    def _fallback_engines(self, request: SearchRequest, used_engines: list[str]) -> list[str]:
        candidates: list[str] = []
        if request.category == "general":
            candidates = ["wikipedia", "stackoverflow", "github"]
        elif request.category == "code":
            candidates = ["stackoverflow", "github", "duckduckgo_lite"]
        elif request.category == "academic":
            candidates = ["wikipedia", "duckduckgo_lite"]
        elif request.category == "reference":
            candidates = ["wikipedia", "duckduckgo_lite"]
        elif request.category == "news":
            candidates = ["google_news_rss", "duckduckgo_lite"]
        else:
            candidates = ["duckduckgo_lite"]
        return [name for name in candidates if name in self.adapters and name not in used_engines]
