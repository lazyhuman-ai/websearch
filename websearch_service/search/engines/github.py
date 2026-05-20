from __future__ import annotations

import httpx

from websearch_service.search.engines.base import SearchEngine
from websearch_service.search.engines.common import GITHUB_LINK_RE, clean_snippet, strip_tags
from websearch_service.search.types import RawSearchHit, SearchRequest


class GitHubEngine(SearchEngine):
    name = "github"
    source_type = "code"

    def supports(self, request: SearchRequest) -> bool:
        return request.category in {"code", "auto"} or any(token in request.query.lower() for token in ("github", "repo", "issue", "library", "sdk", "debug"))

    def build_headers(self, request: SearchRequest) -> dict[str, str]:
        headers = super().build_headers(request)
        headers.update({"Referer": "https://github.com/"})
        return headers

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://github.com/search",
            params={"q": request.effective_query(), "type": "repositories", "p": request.page},
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for path, title_html, after_html in GITHUB_LINK_RE.findall(response.text):
            title = strip_tags(title_html)
            path_parts = [part for part in path.split("/") if part]
            if not title or len(path_parts) != 2 or any(part in {"search", "features", "topics", "collections"} for part in path_parts):
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
