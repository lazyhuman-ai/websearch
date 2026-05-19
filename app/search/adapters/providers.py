from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.search.adapters.base import SearchAdapter
from app.search.normalize import clean_text
from app.search.types import RawSearchHit, SearchRequest


TAG_RE = re.compile(r"<[^>]+>")
GOOGLE_LINK_RE = re.compile(r'href="/url\?q=(https?://[^"&]+)[^"]*"[^>]*>(.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)
GOOGLE_FALLBACK_RE = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)
ANCHOR_RE = re.compile(r'<a[^>]+href="(?P<url>https?://[^"]+)"[^>]*>(?P<title>.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)
GITHUB_LINK_RE = re.compile(r'<a[^>]+href="(/[^"]+)"[^>]*class="[^"]*v-align-middle[^"]*"[^>]*>(.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _strip_tags(value: str) -> str:
    return clean_text(TAG_RE.sub(" ", value or ""))


def _generic_hits(html: str, engine: str, *, limit: int, host_filter: str | None = None) -> list[RawSearchHit]:
    hits: list[RawSearchHit] = []
    for match in ANCHOR_RE.finditer(html):
        url = clean_text(match.group("url"))
        title = _strip_tags(match.group("title"))
        snippet = _strip_tags(match.group("after"))[:320]
        if not url or not title:
            continue
        if host_filter and host_filter not in url:
            continue
        hits.append(RawSearchHit(title=title, url=url, snippet=snippet, engine=engine, engines=[engine]))
        if len(hits) >= limit * 3:
            break
    return hits


def _time_suffix(value: str) -> str:
    return {
        "day": "d",
        "week": "w",
        "month": "m",
        "year": "y",
    }.get(value, "")


class GoogleWebAdapter(SearchAdapter):
    name = "google_web"

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        params = {"q": request.effective_query(), "hl": request.language, "start": max(0, (request.page - 1) * 10)}
        suffix = _time_suffix(request.time_range)
        if suffix:
            params["tbs"] = f"qdr:{suffix}"
        return await client.get("https://www.google.com/search", params=params)

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for url, title_html, after_html in GOOGLE_LINK_RE.findall(response.text):
            title = _strip_tags(title_html)
            if not title:
                continue
            snippet = _strip_tags(after_html)[:320]
            hits.append(RawSearchHit(title=title, url=clean_text(url), snippet=snippet, engine=self.name, engines=[self.name]))
            if len(hits) >= request.max_results:
                break
        if hits:
            return hits
        for url, title_html, after_html in GOOGLE_FALLBACK_RE.findall(response.text):
            cleaned_url = clean_text(url)
            if "google." in cleaned_url:
                continue
            title = _strip_tags(title_html)
            if not title:
                continue
            snippet = _strip_tags(after_html)[:320]
            hits.append(RawSearchHit(title=title, url=cleaned_url, snippet=snippet, engine=self.name, engines=[self.name]))
            if len(hits) >= request.max_results:
                break
        return hits


class BingWebAdapter(SearchAdapter):
    name = "bing_web"

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        params = {"q": request.effective_query(), "setlang": request.language, "first": max(1, ((request.page - 1) * 10) + 1)}
        suffix = _time_suffix(request.time_range)
        if suffix:
            params["filters"] = f"ex1:\"ez{suffix}\""
        return await client.get("https://www.bing.com/search", params=params)

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        hits = _generic_hits(response.text, self.name, limit=request.max_results)
        return [hit for hit in hits if "bing.com/" not in hit.url][: request.max_results]


class BraveWebAdapter(SearchAdapter):
    name = "brave_web"

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        params = {"q": request.effective_query()}
        return await client.get("https://search.brave.com/search", params=params)

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        hits = _generic_hits(response.text, self.name, limit=request.max_results)
        return [hit for hit in hits if "search.brave.com/" not in hit.url][: request.max_results]


class DuckDuckGoLiteAdapter(SearchAdapter):
    name = "duckduckgo_lite"

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        params = {"q": request.effective_query()}
        if request.page > 1:
            params["s"] = (request.page - 1) * 30
        return await client.get("https://lite.duckduckgo.com/lite/", params=params)

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        hits = _generic_hits(response.text, self.name, limit=request.max_results)
        return [hit for hit in hits if "duckduckgo.com/" not in hit.url][: request.max_results]


class WikipediaAdapter(SearchAdapter):
    name = "wikipedia"
    source_type = "reference"

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "opensearch",
                "search": request.effective_query(),
                "limit": request.max_results,
                "namespace": 0,
                "format": "json",
            },
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 4:
            return []
        return [
            RawSearchHit(title=clean_text(str(title)), url=clean_text(str(url)), snippet=clean_text(str(snippet)), engine=self.name, engines=[self.name], source_type=self.source_type)
            for title, snippet, url in zip(payload[1] or [], payload[2] or [], payload[3] or [])
        ][: request.max_results]


class ArxivAdapter(SearchAdapter):
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
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        root = ET.fromstring(response.text)
        hits: list[RawSearchHit] = []
        for entry in root.findall("atom:entry", ARXIV_NS):
            title = clean_text(entry.findtext("atom:title", default="", namespaces=ARXIV_NS))
            summary = clean_text(entry.findtext("atom:summary", default="", namespaces=ARXIV_NS))
            link = ""
            for candidate in entry.findall("atom:link", ARXIV_NS):
                href = candidate.attrib.get("href", "")
                if href.startswith("http"):
                    link = href
                    break
            published_raw = entry.findtext("atom:published", default="", namespaces=ARXIV_NS)
            published_at = None
            if published_raw:
                try:
                    published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                except ValueError:
                    published_at = None
            hits.append(
                RawSearchHit(
                    title=title,
                    url=link,
                    snippet=summary,
                    engine=self.name,
                    engines=[self.name],
                    published_at=published_at,
                    source_type=self.source_type,
                )
            )
        return [hit for hit in hits if hit.url and hit.title][: request.max_results]


class GitHubAdapter(SearchAdapter):
    name = "github"
    source_type = "code"

    def supports(self, request: SearchRequest) -> bool:
        return request.category in {"code", "auto"} or any(token in request.query.lower() for token in ("github", "repo", "issue", "library", "sdk", "debug"))

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        params = {"q": request.effective_query(), "type": "repositories", "p": request.page}
        return await client.get("https://github.com/search", params=params)

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for path, title_html, after_html in GITHUB_LINK_RE.findall(response.text):
            title = _strip_tags(title_html)
            path_parts = [part for part in path.split("/") if part]
            if not title or len(path_parts) != 2 or any(part in {"search", "features", "topics", "collections"} for part in path_parts):
                continue
            snippet = _strip_tags(after_html)[:320]
            hits.append(
                RawSearchHit(
                    title=title,
                    url=f"https://github.com{path}",
                    snippet=snippet,
                    engine=self.name,
                    engines=[self.name],
                    source_type=self.source_type,
                )
            )
            if len(hits) >= request.max_results:
                break
        return hits


class StackOverflowAdapter(SearchAdapter):
    name = "stackoverflow"
    source_type = "code"

    def supports(self, request: SearchRequest) -> bool:
        return request.category in {"code", "auto"} or any(token in request.query.lower() for token in ("error", "exception", "stack overflow", "stackoverflow", "debug", "permission denied"))

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        return await client.get(
            "https://api.stackexchange.com/2.3/search/advanced",
            params={
                "site": "stackoverflow",
                "pagesize": request.max_results,
                "page": request.page,
                "order": "desc",
                "sort": "relevance",
                "q": request.effective_query(),
                "filter": "default",
            },
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        payload = response.json()
        items = payload.get("items", []) if isinstance(payload, dict) else []
        hits: list[RawSearchHit] = []
        for item in items:
            url = clean_text(str(item.get("link") or ""))
            title = clean_text(str(item.get("title") or ""))
            tags = item.get("tags") or []
            score = item.get("score")
            snippet = "Tags: " + ", ".join(tags[:5]) if tags else ""
            if score is not None:
                snippet = f"{snippet} | Score: {score}".strip(" |")
            if url and title:
                hits.append(
                    RawSearchHit(
                        title=title,
                        url=url,
                        snippet=snippet,
                        engine=self.name,
                        engines=[self.name],
                        source_type=self.source_type,
                    )
                )
        return hits[: request.max_results]


class GoogleNewsRssAdapter(SearchAdapter):
    name = "google_news_rss"
    source_type = "news"

    def supports(self, request: SearchRequest) -> bool:
        return request.category in {"news", "auto"}

    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        query = request.effective_query()
        suffix = _time_suffix(request.time_range)
        if suffix:
            query = f"{query} when:{suffix}"
        return await client.get(
            "https://news.google.com/rss/search",
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        )

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        return _parse_rss(response.text, self.name, limit=request.max_results, source_type=self.source_type)


def _parse_rss(xml_text: str, engine: str, *, limit: int, source_type: str) -> list[RawSearchHit]:
    root = ET.fromstring(xml_text)
    hits: list[RawSearchHit] = []
    for item in root.findall(".//item")[:limit]:
        title = clean_text(item.findtext("title", default=""))
        link = clean_text(item.findtext("link", default=""))
        snippet = clean_text(item.findtext("description", default=""))
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
                    engine=engine,
                    engines=[engine],
                    published_at=published_at,
                    source_type=source_type,
                )
            )
    return hits
