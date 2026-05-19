from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from app.search.engines.base import SearchEngine
from app.search.engines.common import ARXIV_NS, clean_snippet, parse_iso_datetime
from app.search.normalize import clean_text
from app.search.types import RawSearchHit, SearchRequest


class ArxivEngine(SearchEngine):
    name = "arxiv"
    source_type = "academic"

    def supports(self, request: SearchRequest) -> bool:
        return request.category in {"academic", "auto"} or any(token in request.query.lower() for token in ("paper", "arxiv", "benchmark", "survey"))

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{request.effective_query()}",
                "start": max(0, (request.page - 1) * request.max_results),
                "max_results": request.max_results,
            },
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        root = ET.fromstring(response.text)
        hits: list[RawSearchHit] = []
        for entry in root.findall("atom:entry", ARXIV_NS):
            title = clean_text(entry.findtext("atom:title", default="", namespaces=ARXIV_NS))
            summary = clean_snippet(entry.findtext("atom:summary", default="", namespaces=ARXIV_NS), limit=480)
            link = ""
            for candidate in entry.findall("atom:link", ARXIV_NS):
                href = candidate.attrib.get("href", "")
                if href.startswith("http"):
                    link = href
                    break
            hits.append(
                RawSearchHit(
                    title=title,
                    url=link,
                    snippet=summary,
                    published_at=parse_iso_datetime(entry.findtext("atom:published", default="", namespaces=ARXIV_NS)),
                    source_type=self.source_type,
                )
            )
        return [hit for hit in hits if hit.url and hit.title][: request.max_results]
