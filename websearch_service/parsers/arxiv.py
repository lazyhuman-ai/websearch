from __future__ import annotations

import xml.etree.ElementTree as ET
import re

import httpx

from websearch_service.parsers.base import SearchResultParser
from websearch_service.parsers.common import clean_snippet, parse_iso_datetime, strip_tags
from websearch_service.types import RawSearchHit, SearchRequest
from websearch_service.utils import clean_text


ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_HTML_RESULT_RE = re.compile(r'<li[^>]+class="[^"]*\barxiv-result\b[^"]*"[^>]*>(?P<block>.*?)(?=<li[^>]+class="[^"]*\barxiv-result\b|</ol>|$)', re.I | re.S)
ARXIV_HTML_ID_RE = re.compile(r'<p[^>]+class="[^"]*\blist-title\b[^"]*"[^>]*>.*?<a[^>]+href="(?P<url>https?://arxiv\.org/abs/[^"]+)"[^>]*>', re.I | re.S)
ARXIV_HTML_TITLE_RE = re.compile(r'<p[^>]+class="[^"]*\btitle\s+is-5\b[^"]*"[^>]*>(?P<title>.*?)</p>', re.I | re.S)
ARXIV_HTML_ABSTRACT_FULL_RE = re.compile(r'<span[^>]+class="[^"]*\babstract-full\b[^"]*"[^>]*>(?P<abstract>.*)</span>\s*</p>', re.I | re.S)
ARXIV_HTML_ABSTRACT_SHORT_RE = re.compile(r'<span[^>]+class="[^"]*\babstract-short\b[^"]*"[^>]*>(?P<abstract>.*?)(?:<a[^>]*>\s*▽\s*More\s*</a>|</span>)', re.I | re.S)
ARXIV_ABSTRACT_UI_RE = re.compile(r"\s*(?:△\s*Less|▽\s*More|Abstract\s*:)\s*", re.I)


class ArxivParser(SearchResultParser):
    source_type = "academic"

    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        content_type = response.headers.get("content-type", "").lower()
        if "html" in content_type or response.text.lstrip().lower().startswith("<!doctype html"):
            return self._parse_html(response.text, request)
        return self._parse_atom(response.text, request)

    def _parse_atom(self, xml_text: str, request: SearchRequest) -> list[RawSearchHit]:
        root = ET.fromstring(xml_text)
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

    def _parse_html(self, html: str, request: SearchRequest) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        for match in ARXIV_HTML_RESULT_RE.finditer(html):
            block = match.group("block")
            id_match = ARXIV_HTML_ID_RE.search(block)
            title_match = ARXIV_HTML_TITLE_RE.search(block)
            if not id_match or not title_match:
                continue
            abstract_match = ARXIV_HTML_ABSTRACT_FULL_RE.search(block) or ARXIV_HTML_ABSTRACT_SHORT_RE.search(block)
            abstract_html = abstract_match.group("abstract") if abstract_match else ""
            title = strip_tags(title_match.group("title"))
            url = clean_text(id_match.group("url"))
            snippet = ARXIV_ABSTRACT_UI_RE.sub(" ", clean_snippet(abstract_html, limit=480))
            snippet = clean_text(snippet)
            if title and url:
                hits.append(RawSearchHit(title=title, url=url, snippet=snippet, source_type=self.source_type))
            if len(hits) >= request.max_results:
                break
        return hits
