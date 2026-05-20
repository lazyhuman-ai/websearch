from __future__ import annotations

import re

import httpx

from websearch_service.engines.base import SearchEngine
from websearch_service.parsers.stackoverflow import StackOverflowParser
from websearch_service.types import RawSearchHit, SearchRequest


PROVIDER_TOKEN_RE = re.compile(r"\b(?:github|repo|repository|repositories|stackoverflow|stack\s+overflow)\b", re.I)


class StackOverflowEngine(SearchEngine):
    name = "stackoverflow"
    source_type = "code"
    parser = StackOverflowParser()

    def supports(self, request: SearchRequest) -> bool:
        return request.category in {"code", "auto"} or any(token in request.query.lower() for token in ("error", "exception", "stack overflow", "stackoverflow", "debug", "permission denied"))

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://api.stackexchange.com/2.3/search/advanced",
            params={
                "site": "stackoverflow",
                "pagesize": request.max_results,
                "page": request.page,
                "order": "desc",
                "sort": "relevance",
                "q": self._provider_query(request),
                "filter": "default",
            },
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        return self.parser.parse(response, request)

    def _provider_query(self, request: SearchRequest) -> str:
        query = PROVIDER_TOKEN_RE.sub(" ", request.effective_query())
        return " ".join(query.split()) or request.effective_query()
