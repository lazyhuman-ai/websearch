from __future__ import annotations

import httpx

from websearch_service.search.engines.base import SearchEngine
from websearch_service.search.normalize import clean_text
from websearch_service.search.types import RawSearchHit, SearchRequest


class StackOverflowEngine(SearchEngine):
    name = "stackoverflow"
    source_type = "code"

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
                "q": request.effective_query(),
                "filter": "default",
            },
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        payload = response.json()
        items = payload.get("items", []) if isinstance(payload, dict) else []
        hits: list[RawSearchHit] = []
        for item in items:
            url = clean_text(str(item.get("link") or ""))
            title = clean_text(str(item.get("title") or ""))
            tags = item.get("tags") or []
            score = item.get("score")
            snippet = "Tags: " + ", ".join(tags[:5]) if tags else ""
            if score is not None:
                snippet = f"{snippet} | Score: {score}".strip(" |")
            if url and title:
                hits.append(RawSearchHit(title=title, url=url, snippet=snippet, source_type=self.source_type))
        return hits[: request.max_results]
