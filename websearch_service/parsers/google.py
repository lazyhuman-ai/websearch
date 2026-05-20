from __future__ import annotations

import re

import httpx

from websearch_service.parsers.base import SearchResultParser
from websearch_service.parsers.common import clean_snippet, strip_tags
from websearch_service.types import RawSearchHit, SearchRequest
from websearch_service.utils import clean_text


GOOGLE_LINK_RE = re.compile(r'href="/url\?q=(https?://[^"&]+)[^"]*"[^>]*>(.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)
GOOGLE_FALLBACK_RE = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)


class GoogleWebParser(SearchResultParser):
    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for url, title_html, after_html in GOOGLE_LINK_RE.findall(response.text):
            title = strip_tags(title_html)
            if not title:
                continue
            hits.append(RawSearchHit(title=title, url=clean_text(url), snippet=clean_snippet(after_html)))
            if len(hits) >= request.max_results:
                break
        if hits:
            return hits
        for url, title_html, after_html in GOOGLE_FALLBACK_RE.findall(response.text):
            cleaned_url = clean_text(url)
            if "google." in cleaned_url:
                continue
            title = strip_tags(title_html)
            if not title:
                continue
            hits.append(RawSearchHit(title=title, url=cleaned_url, snippet=clean_snippet(after_html)))
            if len(hits) >= request.max_results:
                break
        return hits
