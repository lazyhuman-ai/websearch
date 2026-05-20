from __future__ import annotations

import httpx

from websearch_service.engines.base import SearchEngine
from websearch_service.parsers.duckduckgo import DuckDuckGoLiteParser
from websearch_service.types import RawSearchHit, SearchAdapterError, SearchRequest


class DuckDuckGoLiteEngine(SearchEngine):
    name = "duckduckgo_lite"
    parser = DuckDuckGoLiteParser(name)

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
        return self.parser.parse(response, request)
