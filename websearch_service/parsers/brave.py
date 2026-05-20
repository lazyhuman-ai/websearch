from __future__ import annotations

import re

import httpx

from websearch_service.parsers.base import SearchResultParser
from websearch_service.parsers.common import clean_snippet, generic_html_hits, strip_tags
from websearch_service.types import RawSearchHit, SearchRequest
from websearch_service.utils import clean_text


BRAVE_RESULT_RE = re.compile(r'<div[^>]+class="[^"]*\bsnippet\b[^"]*"[^>]+data-type="web"[^>]*>(?P<block>.*?)(?=<div[^>]+class="[^"]*\bsnippet\b[^"]*"[^>]+data-type="web"|</main>|$)', re.I | re.S)
BRAVE_LINK_RE = re.compile(r'<a[^>]+href="(?P<url>https?://[^"]+)"[^>]*>(?P<body>.*?)</a>', re.I | re.S)
BRAVE_TITLE_RE = re.compile(r'<div[^>]+class="[^"]*\btitle\b[^"]*"[^>]*(?:title="(?P<title_attr>[^"]*)")?[^>]*>(?P<title>.*?)</div>', re.I | re.S)
BRAVE_SNIPPET_RE = re.compile(r'<div[^>]+class="[^"]*\bgeneric-snippet\b[^"]*"[^>]*>(?P<snippet>.*?)(?=</div>\s*</div>|</div>\s*<!--)', re.I | re.S)


class BraveWebParser(SearchResultParser):
    def __init__(self, engine_name: str) -> None:
        self.engine_name = engine_name

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        parsed_hits = self._parse_result_blocks(response.text, request)
        if parsed_hits:
            return parsed_hits
        hits = generic_html_hits(response.text, self.engine_name, limit=request.max_results)
        return [hit for hit in hits if "search.brave.com/" not in hit.url][: request.max_results]

    def _parse_result_blocks(self, html: str, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for match in BRAVE_RESULT_RE.finditer(html):
            block = match.group("block")
            link_match = BRAVE_LINK_RE.search(block)
            title_match = BRAVE_TITLE_RE.search(block)
            if not link_match or not title_match:
                continue
            title = clean_text(title_match.group("title_attr") or strip_tags(title_match.group("title")))
            url = clean_text(link_match.group("url"))
            snippet_match = BRAVE_SNIPPET_RE.search(block)
            snippet = clean_snippet(snippet_match.group("snippet") if snippet_match else "")
            if not title or not url or "search.brave.com/" in url:
                continue
            hits.append(RawSearchHit(title=title, url=url, snippet=snippet, engine=self.engine_name, engines=[self.engine_name]))
            if len(hits) >= request.max_results:
                break
        return hits
