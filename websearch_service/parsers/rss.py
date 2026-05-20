from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime

import httpx

from websearch_service.parsers.base import SearchResultParser
from websearch_service.parsers.common import clean_snippet
from websearch_service.types import RawSearchHit, SearchRequest
from websearch_service.utils import clean_text


class RssParser(SearchResultParser):
    def __init__(self, engine_name: str, *, source_type: str) -> None:
        self.engine_name = engine_name
        self.source_type = source_type

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        root = ET.fromstring(response.text)
        hits: list[RawSearchHit] = []
        for item in root.findall(".//item")[: request.max_results]:
            title = clean_text(item.findtext("title", default=""))
            link = clean_text(item.findtext("link", default=""))
            snippet = clean_snippet(item.findtext("description", default=""))
            published_at = None
            published_raw = item.findtext("pubDate", default="")
            if published_raw:
                try:
                    published_at = parsedate_to_datetime(published_raw)
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    published_at = None
            if title and link:
                hits.append(
                    RawSearchHit(
                        title=title,
                        url=link,
                        snippet=snippet,
                        engine=self.engine_name,
                        engines=[self.engine_name],
                        published_at=published_at,
                        source_type=self.source_type,
                    )
                )
        return hits
