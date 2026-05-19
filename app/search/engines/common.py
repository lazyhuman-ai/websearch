from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from app.search.normalize import clean_text
from app.search.types import RawSearchHit


TAG_RE = re.compile(r"<[^>]+>")
GOOGLE_LINK_RE = re.compile(r'href="/url\?q=(https?://[^"&]+)[^"]*"[^>]*>(.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)
GOOGLE_FALLBACK_RE = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)
ANCHOR_RE = re.compile(r'<a[^>]+href="(?P<url>https?://[^"]+)"[^>]*>(?P<title>.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)
GITHUB_LINK_RE = re.compile(r'<a[^>]+href="(/[^"]+)"[^>]*class="[^"]*v-align-middle[^"]*"[^>]*>(.*?)</a>(?P<after>.*?)(?=(?:<a[^>]+href=)|$)', re.I | re.S)
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}
SNIPPET_NOISE_RE = re.compile(
    r"\b(?:cached|translate this page|similar pages|view all|more results|feedback|images|videos|news)\b",
    re.I,
)
SENTENCE_END_RE = re.compile(r"(?<=[.!?。！？])\s+")


def strip_tags(value: str) -> str:
    return clean_text(TAG_RE.sub(" ", value or ""))


def clean_snippet(value: str, *, limit: int = 320) -> str:
    text = strip_tags(value)
    if not text:
        return ""
    text = SNIPPET_NOISE_RE.sub(" ", text)
    text = clean_text(text)
    if not text:
        return ""
    parts = [part.strip() for part in SENTENCE_END_RE.split(text) if part.strip()]
    if parts:
        candidate = parts[0]
        if len(candidate) < 40 and len(parts) > 1:
            candidate = f"{candidate} {parts[1]}".strip()
        text = candidate
    return text[:limit].rstrip(" -|,;:")


def generic_hits(html: str, engine: str, *, limit: int, host_filter: str | None = None) -> list[RawSearchHit]:
    hits: list[RawSearchHit] = []
    for match in ANCHOR_RE.finditer(html):
        url = clean_text(match.group("url"))
        title = strip_tags(match.group("title"))
        snippet = clean_snippet(match.group("after"))
        if not url or not title:
            continue
        if host_filter and host_filter not in url:
            continue
        hits.append(RawSearchHit(title=title, url=url, snippet=snippet, engine=engine, engines=[engine]))
        if len(hits) >= limit * 3:
            break
    return hits


def time_suffix(value: str) -> str:
    return {
        "day": "d",
        "week": "w",
        "month": "m",
        "year": "y",
    }.get(value, "")


def parse_rss(xml_text: str, engine: str, *, limit: int, source_type: str) -> list[RawSearchHit]:
    root = ET.fromstring(xml_text)
    hits: list[RawSearchHit] = []
    for item in root.findall(".//item")[:limit]:
        title = clean_text(item.findtext("title", default=""))
        link = clean_text(item.findtext("link", default=""))
        snippet = clean_snippet(item.findtext("description", default=""))
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


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
