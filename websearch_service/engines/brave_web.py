from __future__ import annotations

import httpx

from websearch_service.engines.base import SearchEngine
from websearch_service.parsers.brave import BraveWebParser
from websearch_service.types import RawSearchHit, SearchAdapterError, SearchRequest


class BraveWebEngine(SearchEngine):
    name = "brave_web"
    parser = BraveWebParser(name)

    def max_attempts(self, request: SearchRequest) -> int:
        return 2

    def build_headers(self, request: SearchRequest) -> dict[str, str]:
        headers = super().build_headers(request)
        headers.update(
            {
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            }
        )
        return headers

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://search.brave.com/search",
            params={"q": request.effective_query(), "summary": "0"},
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        if "429 Too Many Requests" in response.text or "Access denied" in response.text:
            raise SearchAdapterError(f"{self.name} blocked_challenge")
        return self.parser.parse(response, request)
