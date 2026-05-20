from __future__ import annotations

import re
from urllib.parse import unquote

import httpx

from websearch_service.parsers.base import SearchResultParser
from websearch_service.parsers.common import clean_snippet, strip_tags
from websearch_service.types import RawSearchHit, SearchRequest
from websearch_service.utils import clean_text, unwrap_redirect_url


DDG_LITE_RESULT_RE = re.compile(
    r"<a(?=[^>]*class=['\"]result-link['\"])(?=[^>]*href=['\"](?P<url>[^'\"]+)['\"])[^>]*>(?P<title>.*?)</a>.*?<td[^>]+class=['\"]result-snippet['\"][^>]*>(?P<snippet>.*?)</td>",
    re.I | re.S,
)


class DuckDuckGoLiteParser(SearchResultParser):
    def __init__(self, engine_name: str) -> None:
        self.engine_name = engine_name

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for match in DDG_LITE_RESULT_RE.finditer(response.text):
            url = unwrap_redirect_url(unquote(clean_text(match.group("url"))))
            title = strip_tags(match.group("title"))
            snippet = clean_snippet(match.group("snippet") or "")
            if not url or not title:
                continue
            hits.append(RawSearchHit(title=title, url=url, snippet=snippet, engine=self.engine_name, engines=[self.engine_name]))
            if len(hits) >= request.max_results:
                break
        return hits
