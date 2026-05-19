from __future__ import annotations

import httpx

from app.search.engines.base import SearchEngine
from app.search.engines.common import generic_hits
from app.search.types import RawSearchHit, SearchAdapterError, SearchRequest


class DuckDuckGoLiteEngine(SearchEngine):
    name = "duckduckgo_lite"

    def max_attempts(self, request: SearchRequest) -> int:
        return 2

    def build_headers(self, request: SearchRequest) -> dict[str, str]:
        headers = super().build_headers(request)
        headers.update({"Referer": "https://duckduckgo.com/"})
        return headers

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        params = {"q": request.effective_query()}
        if request.page > 1:
            params["s"] = (request.page - 1) * 30
        return await client.get("https://lite.duckduckgo.com/lite/", params=params, headers=self.build_headers(request))

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        if "anomaly-modal" in response.text or "Unfortunately, bots use DuckDuckGo too." in response.text:
            raise SearchAdapterError(f"{self.name} blocked_challenge")
        hits = generic_hits(response.text, self.name, limit=request.max_results)
        return [hit for hit in hits if "duckduckgo.com/" not in hit.url][: request.max_results]
