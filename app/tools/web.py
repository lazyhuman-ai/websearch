from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import trafilatura

from app.config import get_settings
from app.schemas import SearchResult, WebDocument


TOKEN_RE = re.compile(r"[a-zA-Z0-9]{2,}")
MULTI_BLANK_RE = re.compile(r"\n{3,}")
logger = logging.getLogger(__name__)


class WebSearchClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._search_cache: dict[tuple[str, int, str], tuple[float, list[SearchResult]]] = {}
        self._search_semaphore = threading.BoundedSemaphore(max(1, self.settings.max_concurrent_searches))
        self._request_lock = threading.Lock()
        self._last_search_request_at = 0.0

    def search(self, query: str, *, max_results: int | None = None) -> list[SearchResult]:
        self.ensure_searxng()
        endpoint = f"{self.settings.searxng_base_url.rstrip('/')}/search"
        categories = self.settings.searxng_categories.strip()
        limit = min(max_results or self.settings.search_max_results, self.settings.max_results_per_query)
        cache_key = (query.strip().lower(), limit, categories)
        cached = self._get_cached_results(cache_key)
        if cached is not None:
            return cached

        last_error: RuntimeError | None = None
        with self._search_semaphore:
            for engine_group in self._select_engine_groups(query):
                self._respect_request_interval()
                params = {"q": query, "format": "json", "engines": ",".join(engine_group)}
                if categories:
                    params["categories"] = categories
                try:
                    with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
                        response = client.get(endpoint, params=params)
                        response.raise_for_status()
                        payload = response.json()
                except httpx.HTTPError as exc:
                    last_error = RuntimeError(f"SearXNG search failed for engines {engine_group}: {exc}")
                    logger.warning("search_request_failed query=%s engines=%s error=%s", query, engine_group, exc)
                    continue
                except ValueError:
                    last_error = RuntimeError("SearXNG returned invalid JSON")
                    logger.warning("search_invalid_json query=%s engines=%s", query, engine_group)
                    continue

                results = self._extract_results(payload, limit)
                logger.info(
                    "search_attempt query=%s engines=%s results=%s unresponsive=%s",
                    query,
                    engine_group,
                    len(results),
                    payload.get("unresponsive_engines") or [],
                )
                if results:
                    self._set_cached_results(cache_key, results)
                    return results

        if last_error is not None:
            raise last_error
        self._set_cached_results(cache_key, [])
        return []

    def ensure_searxng(self) -> None:
        if self._is_searxng_ready():
            return
        if not self.settings.searxng_auto_start:
            raise RuntimeError(
                "SearXNG is not reachable and auto-start is disabled. "
                "Start it with `docker compose up -d searxng`."
            )
        self._start_searxng()
        deadline = time.time() + self.settings.searxng_startup_timeout_seconds
        while time.time() < deadline:
            if self._is_searxng_ready():
                return
            time.sleep(1.0)
        raise RuntimeError("SearXNG did not become ready after auto-start.")

    def read_pages(self, pages: list[dict[str, str]]) -> list[WebDocument]:
        return [self.read_page(**page) for page in pages]

    def read_page(
        self,
        *,
        url: str,
        source_id: str,
        title: str = "",
        snippet: str = "",
        engine: str = "searxng",
    ) -> WebDocument:
        try:
            with httpx.Client(
                timeout=self.settings.request_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": self.settings.user_agent},
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                html = response.text
        except httpx.HTTPError as exc:
            return WebDocument(
                source_id=source_id,
                title=title or url,
                url=url,
                snippet=snippet,
                engine=engine,
                success=False,
                error=f"fetch_error: {exc}",
            )

        extracted = trafilatura.extract(
            html,
            url=url,
            include_links=False,
            include_images=False,
            output_format="markdown",
            favor_recall=True,
            deduplicate=True,
        )
        if not extracted:
            return WebDocument(
                source_id=source_id,
                title=title or url,
                url=url,
                snippet=snippet,
                engine=engine,
                success=False,
                error="extract_error: empty_content",
            )

        return WebDocument(
            source_id=source_id,
            title=title or url,
            url=url,
            snippet=snippet,
            engine=engine,
            content=self._clean_text(extracted),
            success=True,
        )

    def search_and_read(self, query: str, *, max_results: int | None = None) -> tuple[list[SearchResult], list[WebDocument]]:
        results = self.search(query, max_results=max_results)
        pages = [
            {"source_id": item.source_id, "url": str(item.url), "title": item.title, "snippet": item.snippet, "engine": item.engine}
            for item in results[: self.settings.search_read_results]
        ]
        return results, self.read_pages(pages)

    def rerank(self, query: str, documents: list[WebDocument], *, top_k: int | None = None) -> list[WebDocument]:
        ranked = self.rank_all(query, documents)
        seen_domains: set[str] = set()
        deduped: list[WebDocument] = []
        for document in ranked:
            domain = urlparse(str(document.url)).netloc.lower()
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            deduped.append(document)
        return deduped[: (top_k or self.settings.rerank_top_k)]

    def rank_all(self, query: str, documents: list[WebDocument]) -> list[WebDocument]:
        ranked: list[WebDocument] = []
        for document in documents:
            if not document.success or not document.content.strip():
                continue
            document.score = self._score_document(query, document)
            if document.score <= 0:
                continue
            ranked.append(document)
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    def _normalize_search_result(self, item: dict[str, Any], index: int) -> SearchResult | None:
        url = item.get("url")
        title = item.get("title") or url
        if not url or not title:
            return None
        engines = item.get("engines") or []
        engine = ", ".join(engines) if isinstance(engines, list) else str(engines or "searxng")
        return SearchResult(
            source_id=f"S{index}",
            title=title.strip(),
            url=url,
            snippet=(item.get("content") or item.get("snippet") or "").strip(),
            engine=engine,
        )

    def _extract_results(self, payload: dict[str, Any], limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        for index, item in enumerate((payload.get("results") or [])[:limit], start=1):
            normalized = self._normalize_search_result(item, index)
            if normalized is not None:
                results.append(normalized)
        return results

    def _clean_text(self, text: str) -> str:
        text = MULTI_BLANK_RE.sub("\n\n", text.strip())
        if len(text) <= self.settings.max_document_chars:
            return text
        return text[: self.settings.max_document_chars].rstrip() + "\n\n[TRUNCATED]"

    def _score_document(self, query: str, document: WebDocument) -> float:
        query_tokens = TOKEN_RE.findall(query.lower())
        if not query_tokens:
            return 0.0
        doc_tokens = TOKEN_RE.findall(" ".join([document.title, document.snippet, document.content]).lower())
        if not doc_tokens:
            return 0.0
        query_counts = Counter(query_tokens)
        doc_counts = Counter(doc_tokens)
        overlap = sum(min(doc_counts[token], count) for token, count in query_counts.items())
        coverage = overlap / len(query_tokens)
        length_bonus = min(1.0, math.log(len(doc_tokens) + 1, 20))
        return round((coverage * 0.8) + (length_bonus * 0.2), 4)

    def _select_engine_groups(self, query: str) -> list[tuple[str, ...]]:
        looks_news = bool(re.search(r"\b(latest|lastest|recent|today|news|202[4-9])\b", query, re.I))
        if looks_news:
            return [
                ("bing news", "reuters", "wikinews"),
                ("google news", "yahoo news"),
                ("qwant news", "mojeek news"),
            ]
        return [
            ("bing", "google"),
            ("yahoo", "qwant"),
            ("mojeek", "wikipedia"),
        ]

    def _get_cached_results(self, cache_key: tuple[str, int, str]) -> list[SearchResult] | None:
        cached = self._search_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, results = cached
        if time.monotonic() >= expires_at:
            self._search_cache.pop(cache_key, None)
            return None
        return results

    def _set_cached_results(self, cache_key: tuple[str, int, str], results: list[SearchResult]) -> None:
        self._search_cache[cache_key] = (
            time.monotonic() + max(1, self.settings.cache_ttl_seconds),
            results,
        )

    def _respect_request_interval(self) -> None:
        with self._request_lock:
            now = time.monotonic()
            wait_seconds = self.settings.request_interval_seconds - (now - self._last_search_request_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_search_request_at = time.monotonic()

    def _is_searxng_ready(self) -> bool:
        endpoint = f"{self.settings.searxng_base_url.rstrip('/')}/search"
        try:
            with httpx.Client(timeout=min(3.0, self.settings.request_timeout_seconds)) as client:
                response = client.get(endpoint, params={"q": "healthcheck", "format": "json"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return False
        return isinstance(payload.get("results"), list)

    def _start_searxng(self) -> None:
        if shutil.which("docker") is None:
            raise RuntimeError("SearXNG is not reachable and Docker is not installed or not on PATH.")

        compose_dir = Path(self.settings.searxng_compose_dir)
        if not compose_dir.is_absolute():
            compose_dir = Path.cwd() / compose_dir
        if not compose_dir.exists():
            raise RuntimeError(f"SearXNG compose directory does not exist: {compose_dir}")

        command = ["docker", "compose", "up", "-d", self.settings.searxng_service_name]
        try:
            result = subprocess.run(
                command,
                cwd=str(compose_dir),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"Failed to execute Docker: {exc}") from exc

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or "unknown docker compose error"
            raise RuntimeError(f"Failed to auto-start SearXNG: {detail}")
