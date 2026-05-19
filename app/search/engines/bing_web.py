from __future__ import annotations

import httpx

from app.search.engines.base import SearchEngine
from app.search.engines.common import generic_hits, time_suffix
from app.search.types import RawSearchHit, SearchAdapterError, SearchRequest


class BingWebEngine(SearchEngine):
    name = "bing_web"

    def max_attempts(self, request: SearchRequest) -> int:
        return 2

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        params = {"q": request.effective_query(), "setlang": request.language, "first": max(1, ((request.page - 1) * 10) + 1), "count": max(10, request.max_results), "ensearch": 1}
        suffix = time_suffix(request.time_range)
        if suffix:
            params["filters"] = f"ex1:\"ez{suffix}\""
        return await client.get("https://www.bing.com/search", params=params, headers=self.build_headers(request))

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        if "Our systems have detected unusual traffic" in response.text or "bnp_container" in response.text and "captcha" in response.text.lower():
            raise SearchAdapterError(f"{self.name} blocked_challenge")
        hits = generic_hits(response.text, self.name, limit=request.max_results)
        return [hit for hit in hits if "bing.com/" not in hit.url][: request.max_results]
