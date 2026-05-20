from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
import random

import httpx

from websearch_service.search.engine_config import load_engine_config
from websearch_service.search.types import RawSearchHit, SearchAdapterError, SearchRequest


class SearchEngine(ABC):
    name: str
    source_type: str = "web"

    def supports(self, request: SearchRequest) -> bool:
        return True

    def build_headers(self, request: SearchRequest) -> dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": request.language,
            "DNT": "1",
        }
        profiles = load_engine_config(request.engine_config_path).headers_for(self.name)
        if profiles:
            headers.update(random.choice(profiles))
        return headers

    def normalize(self, hit: RawSearchHit) -> RawSearchHit:
        hit.engine = self.name
        if not hit.engines:
            hit.engines = [self.name]
        if not hit.source_type:
            hit.source_type = self.source_type
        return hit

    def clean_hits(self, hits: list[RawSearchHit], request: SearchRequest) -> list[RawSearchHit]:
        return [self.normalize(hit) for hit in hits]

    def max_attempts(self, request: SearchRequest) -> int:
        return 1

    async def search(self, client: httpx.AsyncClient, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for request_index in range(max(1, request.max_engine_requests)):
            paged_request = replace(request, page=max(1, request.page + request_index))
            batch = await self._search_once(client, paged_request)
            if not batch:
                break
            hits.extend(batch)
        return self.clean_hits(hits, request)

    async def _search_once(self, client: httpx.AsyncClient, request: SearchRequest) -> list[RawSearchHit]:
        last_error: Exception | None = None
        max_attempts = self.max_attempts(request)
        for attempt in range(max_attempts):
            try:
                response = await self.fetch(client, request)
                response.raise_for_status()
                return self.parse(response, request)
            except httpx.HTTPStatusError as exc:
                last_error = SearchAdapterError(f"{self.name} http_status={exc.response.status_code}")
                if exc.response.status_code not in {408, 429, 500, 502, 503, 504} or attempt + 1 >= max_attempts:
                    raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = SearchAdapterError(f"{self.name} http_error={exc}")
                if attempt + 1 >= max_attempts:
                    raise last_error from exc
            except Exception as exc:  # pragma: no cover
                raise SearchAdapterError(f"{self.name} parse_error={exc}") from exc
        if last_error is not None:
            raise last_error
        raise SearchAdapterError(f"{self.name} unknown_error")

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        raise NotImplementedError

    @abstractmethod
    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        raise NotImplementedError
