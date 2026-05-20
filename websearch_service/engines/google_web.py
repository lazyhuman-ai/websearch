from __future__ import annotations

import httpx

from websearch_service.engines.base import SearchEngine
from websearch_service.parsers.common import time_suffix
from websearch_service.parsers.google import GoogleWebParser
from websearch_service.types import RawSearchHit, SearchAdapterError, SearchRequest


class GoogleWebEngine(SearchEngine):
    name = "google_web"
    parser = GoogleWebParser()

    def max_attempts(self, request: SearchRequest) -> int:
        return 2

    def build_headers(self, request: SearchRequest) -> dict[str, str]:
        headers = super().build_headers(request)
        headers.update({"Referer": "https://www.google.com/"})
        return headers

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        params = {"q": request.effective_query(), "hl": request.language, "num": max(10, request.max_results), "start": max(0, (request.page - 1) * 10), "pws": 0}
        suffix = time_suffix(request.time_range)
        if suffix:
            params["tbs"] = f"qdr:{suffix}"
        return await client.get("https://www.google.com/search", params=params, headers=self.build_headers(request))

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        if "Please click" in response.text or "/httpservice/retry/enablejs" in response.text or "<title>Google Search</title>" in response.text:
            raise SearchAdapterError(f"{self.name} blocked_challenge")
        return self.parser.parse(response, request)
