from __future__ import annotations

import httpx

from websearch_service.engines.base import SearchEngine
from websearch_service.parsers.common import time_suffix
from websearch_service.parsers.rss import RssParser
from websearch_service.types import RawSearchHit, SearchRequest


class GoogleNewsRssEngine(SearchEngine):
    name = "google_news_rss"
    source_type = "news"
    parser = RssParser(name, source_type=source_type)

    def supports(self, request: SearchRequest) -> bool:
        return request.category in {"news", "auto"}

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        query = request.effective_query()
        suffix = time_suffix(request.time_range)
        if suffix:
            query = f"{query} when:{suffix}"
        return await client.get(
            "https://news.google.com/rss/search",
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        return self.parser.parse(response, request)
