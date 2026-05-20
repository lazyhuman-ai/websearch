from __future__ import annotations

import httpx

from websearch_service.engines.base import SearchEngine
from websearch_service.parsers.wikipedia import WikipediaParser
from websearch_service.types import RawSearchHit, SearchRequest


class WikipediaEngine(SearchEngine):
    name = "wikipedia"
    source_type = "reference"
    parser = WikipediaParser()

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": request.effective_query(),
                "srlimit": request.max_results,
                "srnamespace": 0,
                "format": "json",
            },
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        return self.parser.parse(response, request)
