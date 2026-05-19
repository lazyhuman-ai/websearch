from __future__ import annotations

import httpx

from app.search.engines.base import SearchEngine
from app.search.engines.common import generic_hits
from app.search.types import RawSearchHit, SearchAdapterError, SearchRequest


class BraveWebEngine(SearchEngine):
    name = "brave_web"

    def max_attempts(self, request: SearchRequest) -> int:
        return 2

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://search.brave.com/search",
            params={"q": request.effective_query()},
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        if "429 Too Many Requests" in response.text or "captcha" in response.text.lower() or "Access denied" in response.text:
            raise SearchAdapterError(f"{self.name} blocked_challenge")
        hits = generic_hits(response.text, self.name, limit=request.max_results)
        return [hit for hit in hits if "search.brave.com/" not in hit.url][: request.max_results]
