from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from websearch_service.config import Settings
from websearch_service.engines.base import SearchEngine
from websearch_service.types import RawSearchHit, SearchRequest
from websearch_service.utils import (
    build_async_client,
    canonical_result_key,
    choose_user_agent,
    has_meaningful_overlap,
    looks_low_quality,
    normalize_url,
)


@dataclass(slots=True)
class CollectedHits:
    hits: list[RawSearchHit]
    planned_names: list[str]
    failures: dict[str, str]
    diagnostics: dict[str, dict[str, object]]


class SearchCollector:
    def __init__(
        self,
        settings: Settings,
        engines: dict[str, SearchEngine],
        *,
        is_banned: Callable[[str], bool],
        record_success: Callable[[str, int], None],
        record_failure: Callable[[str, str], None],
    ) -> None:
        self.settings = settings
        self.engines = engines
        self.is_banned = is_banned
        self.record_success = record_success
        self.record_failure = record_failure

    async def collect(self, request: SearchRequest, engine_names: list[str]) -> CollectedHits:
        tasks = []
        planned_names = []
        for name in engine_names:
            if self.is_banned(name):
                continue
            engine = self.engines.get(name)
            if engine is None or not engine.supports(request):
                continue
            tasks.append(self._run_engine(engine, request))
            planned_names.append(name)

        results = (
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.settings.search_total_timeout_seconds,
            )
            if tasks
            else []
        )
        hits: list[RawSearchHit] = []
        failures: dict[str, str] = {}
        diagnostics: dict[str, dict[str, object]] = {}
        for name, result in zip(planned_names, results):
            if isinstance(result, Exception):
                failures[name] = str(result)
                self.record_failure(name, str(result))
                diagnostics[name] = {
                    "raw_hits": 0,
                    "filtered_hits": 0,
                    "dropped_hits": 0,
                    "error": str(result),
                }
                continue
            filtered_hits, engine_diag = result
            diagnostics[name] = engine_diag
            self.record_success(name, len(filtered_hits))
            hits.extend(filtered_hits)
        return CollectedHits(hits=hits, planned_names=planned_names, failures=failures, diagnostics=diagnostics)

    async def _run_engine(self, engine: SearchEngine, request: SearchRequest) -> tuple[list[RawSearchHit], dict[str, object]]:
        user_agent = choose_user_agent(self.settings.user_agent, self.settings.search_user_agent_rotation)
        async with build_async_client(
            timeout_seconds=self.settings.search_engine_timeout_seconds,
            follow_redirects=True,
            user_agent=user_agent,
            accept_language=request.language,
        ) as client:
            raw_hits = await engine.search(client, request)
        hits = self._filter_hits(request, raw_hits)
        return hits, {
            "raw_hits": len(raw_hits),
            "filtered_hits": len(hits),
            "dropped_hits": max(0, len(raw_hits) - len(hits)),
            "error": None,
        }

    def _filter_hits(self, request: SearchRequest, raw_hits: list[RawSearchHit]) -> list[RawSearchHit]:
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

    def _matches_site(self, url: str, site: str) -> bool:
        from urllib.parse import urlparse

        host = urlparse(url).netloc.lower()
        normalized = site.lower().strip()
        return host == normalized or host.endswith(f".{normalized}")
