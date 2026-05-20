from __future__ import annotations

from dataclasses import replace

import httpx

from websearch_service.engines.base import SearchEngine
from websearch_service.parsers.arxiv import ArxivParser
from websearch_service.types import RawSearchHit, SearchAdapterError, SearchRequest


class ArxivEngine(SearchEngine):
    name = "arxiv"
    source_type = "academic"
    parser = ArxivParser()

    def max_attempts(self, request: SearchRequest) -> int:
        return 2

    def supports(self, request: SearchRequest) -> bool:
        return request.category in {"academic", "auto"} or any(token in request.query.lower() for token in ("paper", "arxiv", "benchmark", "survey"))

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
        try:
            response = await self._fetch_atom(client, request)
            response.raise_for_status()
            return self.parse(response, request)
        except (httpx.HTTPError, SearchAdapterError):
            response = await self._fetch_html(client, request, abstracts="hide")
            response.raise_for_status()
            return self.parse(response, request)

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await self._fetch_atom(client, request)

    async def _fetch_atom(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{request.effective_query()}",
                "start": max(0, (request.page - 1) * request.max_results),
                "max_results": request.max_results,
            },
            headers=self.build_headers(request),
        )

    async def _fetch_html(self, client: httpx.AsyncClient, request: SearchRequest, *, abstracts: str) -> httpx.Response:
        return await client.get(
            "https://arxiv.org/search/",
            params={
                "query": request.effective_query(),
                "searchtype": "all",
                "abstracts": abstracts,
                "size": max(25, request.max_results),
                "start": max(0, (request.page - 1) * request.max_results),
            },
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        return self.parser.parse(response, request)
