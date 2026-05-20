from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from websearch_service.config import Settings
from websearch_service.types import RawSearchHit, SearchRequest, SearchResult
from websearch_service.utils import canonical_result_key, score_hit
from websearch_service.fetch import get_url


class SearchAggregator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def merge_and_rank(self, request: SearchRequest, hits: Iterable[RawSearchHit]) -> list[SearchResult]:
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

    def resolve_result_urls(self, results: list[SearchResult], *, include_content: bool) -> list[SearchResult]:
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

    def needs_quality_fallback(self, request: SearchRequest, results: list[SearchResult]) -> bool:
        if not results:
            return True
        if request.site:
            return len(results) < min(2, request.max_results)
        return max(item.score for item in results) < 0.18

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
