from __future__ import annotations

import re

import httpx

from websearch_service.engines.base import SearchEngine
from websearch_service.parsers.github import GitHubParser
from websearch_service.types import RawSearchHit, SearchRequest


PROVIDER_TOKEN_RE = re.compile(r"\b(?:github|repo|repository|repositories)\b", re.I)


class GitHubEngine(SearchEngine):
    name = "github"
    source_type = "code"
    parser = GitHubParser()

    def supports(self, request: SearchRequest) -> bool:
        return request.category in {"code", "auto"} or any(token in request.query.lower() for token in ("github", "repo", "issue", "library", "sdk", "debug"))

    def build_headers(self, request: SearchRequest) -> dict[str, str]:
        headers = super().build_headers(request)
        headers.update({"Referer": "https://github.com/"})
        return headers

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://github.com/search",
            params={"q": self._provider_query(request), "type": "repositories", "p": request.page},
            headers=self.build_headers(request),
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        return self.parser.parse(response, request)

    def _provider_query(self, request: SearchRequest) -> str:
        query = PROVIDER_TOKEN_RE.sub(" ", request.effective_query())
        return " ".join(query.split()) or request.effective_query()
