from __future__ import annotations

import re

import httpx

from websearch_service.parsers.base import SearchResultParser
from websearch_service.parsers.common import clean_snippet, strip_tags
from websearch_service.types import RawSearchHit, SearchRequest


GITHUB_LEGACY_LINK_RE = re.compile(r'<a[^>]+href="(/[^"]+)"[^>]*class="[^"]*v-align-middle[^"]*"[^>]*>(.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)
GITHUB_SEARCH_TITLE_RE = re.compile(
    r'<div[^>]+class="[^"]*\bsearch-title\b[^"]*"[^>]*>\s*<a[^>]+href="(?P<path>/[^"]+)"[^>]*>(?P<title>.*?)</a>.*?(?=<div[^>]+class="[^"]*\bsearch-title\b|</main>|$)',
    re.I | re.S,
)
GITHUB_CONTENT_RE = re.compile(r'<div[^>]+class="[^"]*Content-module__Content[^"]*"[^>]*>(?P<snippet>.*?)</div>', re.I | re.S)


class GitHubParser(SearchResultParser):
    source_type = "code"

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        hits = self._parse_current_search(response.text, request)
        if hits:
            return hits
        return self._parse_legacy_search(response.text, request)

    def _parse_current_search(self, html: str, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for match in GITHUB_SEARCH_TITLE_RE.finditer(html):
            path = match.group("path")
            title = strip_tags(match.group("title"))
            if not self._is_repo_path(path) or not title:
                continue
            snippet_match = GITHUB_CONTENT_RE.search(match.group(0))
            hits.append(
                RawSearchHit(
                    title=title,
                    url=f"https://github.com{path}",
                    snippet=clean_snippet(snippet_match.group("snippet") if snippet_match else ""),
                    source_type=self.source_type,
                )
            )
            if len(hits) >= request.max_results:
                break
        return hits

    def _parse_legacy_search(self, html: str, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for path, title_html, after_html in GITHUB_LEGACY_LINK_RE.findall(html):
            title = strip_tags(title_html)
            if not title or not self._is_repo_path(path):
                continue
            hits.append(
                RawSearchHit(
                    title=title,
                    url=f"https://github.com{path}",
                    snippet=clean_snippet(after_html),
                    source_type=self.source_type,
                )
            )
            if len(hits) >= request.max_results:
                break
        return hits

    def _is_repo_path(self, path: str) -> bool:
        path_parts = [part for part in path.split("/") if part]
        if len(path_parts) != 2:
            return False
        return not any(part in {"search", "features", "topics", "collections", "marketplace"} for part in path_parts)
