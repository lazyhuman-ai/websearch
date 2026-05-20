from __future__ import annotations

import httpx

from websearch_service.search.engines.base import SearchEngine
from websearch_service.search.engines.common import clean_snippet
from websearch_service.search.normalize import clean_text
from websearch_service.search.types import RawSearchHit, SearchRequest


class WikipediaEngine(SearchEngine):
    name = "wikipedia"
    source_type = "reference"

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "opensearch",
                "search": request.effective_query(),
                "limit": request.max_results,
                "namespace": 0,
                "format": "json",
            },
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 4:
            return []
        return [
            RawSearchHit(title=clean_text(str(title)), url=clean_text(str(url)), snippet=clean_snippet(str(snippet)), source_type=self.source_type)
            for title, snippet, url in zip(payload[1] or [], payload[2] or [], payload[3] or [])
        ][: request.max_results]
