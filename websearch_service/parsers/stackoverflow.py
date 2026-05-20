from __future__ import annotations

import httpx

from websearch_service.parsers.base import SearchResultParser
from websearch_service.types import RawSearchHit, SearchRequest
from websearch_service.utils import clean_text


class StackOverflowParser(SearchResultParser):
    source_type = "code"

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
