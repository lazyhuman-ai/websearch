from __future__ import annotations

import httpx

from websearch_service.parsers.base import SearchResultParser
from websearch_service.parsers.common import clean_snippet
from websearch_service.types import RawSearchHit, SearchRequest
from websearch_service.utils import clean_text


class WikipediaParser(SearchResultParser):
    source_type = "reference"

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        payload = response.json()
        if isinstance(payload, dict):
            items = payload.get("query", {}).get("search", []) if isinstance(payload.get("query"), dict) else []
            hits: list[RawSearchHit] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = clean_text(str(item.get("title") or ""))
                pageid = item.get("pageid")
                if not title or not pageid:
                    continue
                slug = title.replace(" ", "_")
                hits.append(
                    RawSearchHit(
                        title=title,
                        url=f"https://en.wikipedia.org/wiki/{slug}",
                        snippet=clean_snippet(str(item.get("snippet") or "")),
                        source_type=self.source_type,
                    )
                )
            return hits[: request.max_results]
        if not isinstance(payload, list) or len(payload) < 4:
            return []
        return [
            RawSearchHit(title=clean_text(str(title)), url=clean_text(str(url)), snippet=clean_snippet(str(snippet)), source_type=self.source_type)
            for title, snippet, url in zip(payload[1] or [], payload[2] or [], payload[3] or [])
        ][: request.max_results]
