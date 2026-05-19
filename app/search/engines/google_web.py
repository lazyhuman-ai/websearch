from __future__ import annotations

import httpx

from app.search.engines.base import SearchEngine
from app.search.engines.common import GOOGLE_FALLBACK_RE, GOOGLE_LINK_RE, clean_snippet, strip_tags, time_suffix
from app.search.normalize import clean_text
from app.search.types import RawSearchHit, SearchAdapterError, SearchRequest


class GoogleWebEngine(SearchEngine):
    name = "google_web"

    def max_attempts(self, request: SearchRequest) -> int:
        return 2

    def build_headers(self, request: SearchRequest) -> dict[str, str]:
        headers = super().build_headers(request)
        headers.update({"Referer": "https://www.google.com/"})
        return headers

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        params = {"q": request.effective_query(), "hl": request.language, "num": max(10, request.max_results), "start": max(0, (request.page - 1) * 10), "pws": 0}
        suffix = time_suffix(request.time_range)
        if suffix:
            params["tbs"] = f"qdr:{suffix}"
        return await client.get("https://www.google.com/search", params=params, headers=self.build_headers(request))

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        if "Please click" in response.text or "/httpservice/retry/enablejs" in response.text or "<title>Google Search</title>" in response.text:
            raise SearchAdapterError(f"{self.name} blocked_challenge")
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
