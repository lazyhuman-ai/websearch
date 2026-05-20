from __future__ import annotations

import re

import httpx

from websearch_service.parsers.base import SearchResultParser
from websearch_service.parsers.common import clean_snippet, strip_tags
from websearch_service.types import RawSearchHit, SearchRequest
from websearch_service.utils import clean_text, unwrap_redirect_url


BING_BLOCK_RE = re.compile(r'<li[^>]+class="[^"]*\bb_algo\b[^"]*"[^>]*>(?P<block>.*?)(?=<li[^>]+class="[^"]*\bb_algo\b|</ol>|</main>|$)', re.I | re.S)
BING_TITLE_RE = re.compile(r'<h2[^>]*>\s*<a[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.I | re.S)
BING_SNIPPET_RE = re.compile(r'<div[^>]+class="[^"]*\bb_caption\b[^"]*"[^>]*>.*?<p[^>]*>(?P<snippet>.*?)</p>', re.I | re.S)


class BingWebParser(SearchResultParser):
    def __init__(self, engine_name: str) -> None:
        self.engine_name = engine_name

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for block_match in BING_BLOCK_RE.finditer(response.text):
            block = block_match.group("block")
            title_match = BING_TITLE_RE.search(block)
            if not title_match:
                continue
            url = unwrap_redirect_url(clean_text(title_match.group("url")))
            title = strip_tags(title_match.group("title"))
            snippet_match = BING_SNIPPET_RE.search(block)
            snippet = clean_snippet(snippet_match.group("snippet") if snippet_match else "")
            if not url or not title:
                continue
            hits.append(RawSearchHit(title=title, url=url, snippet=snippet, engine=self.engine_name, engines=[self.engine_name]))
            if len(hits) >= request.max_results:
                break
        return hits
