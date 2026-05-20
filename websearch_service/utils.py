from __future__ import annotations

import math
import random
import re
from base64 import b64decode, urlsafe_b64decode
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from websearch_service.types import RawSearchHit, SearchCategory


TRACKER_PREFIXES = ("utm_",)
TRACKER_KEYS = {
    "ved",
    "ei",
    "gclid",
    "fbclid",
    "msclkid",
    "ref",
    "ref_src",
    "src",
    "spm",
    "igshid",
}
UNWRAP_KEYS = ("uddg", "u", "url", "target", "dest", "destination", "redir", "redirect")
MULTI_SPACE_RE = re.compile(r"\s+")
NON_WORD_RE = re.compile(r"[^a-z0-9]+")
TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "latest",
    "news",
    "of",
    "on",
    "or",
    "recent",
    "the",
    "to",
    "today",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
}
SOURCE_PRIORS = {
    "wikipedia": 0.08,
    "arxiv": 0.1,
    "github": 0.07,
    "stackoverflow": 0.08,
    "google_news_rss": 0.06,
}
TOKEN_ALIASES = {
    "us": ["united", "states"],
    "usa": ["united", "states"],
}
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


def clean_text(text: str) -> str:
    return MULTI_SPACE_RE.sub(" ", unescape(text or "")).strip()


def unwrap_redirect_url(url: str) -> str:
    if not url:
        return ""
    normalized_url = _normalize_relative_url(url.strip())
    parsed = urlparse(normalized_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in UNWRAP_KEYS:
        target = query.get(key)
        if not target:
            continue
        if target.startswith(("http://", "https://", "//")):
            return _normalize_relative_url(target)
        if key == "u":
            decoded_target = _decode_bing_redirect_target(target)
            if decoded_target:
                return decoded_target
    return normalized_url


def normalize_url(url: str, strip_trackers: bool = True) -> str:
    unwrapped = unwrap_redirect_url(url.strip())
    cleaned = strip_tracking_params(unwrapped) if strip_trackers else unwrapped
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def canonical_result_key(url: str, title: str) -> tuple[str, str]:
    normalized_url = normalize_url(url)
    parsed = urlparse(normalized_url)
    return normalized_url, f"{parsed.netloc}|{title_signature(title)}"


def title_signature(title: str) -> str:
    normalized = NON_WORD_RE.sub(" ", clean_text(title).lower()).strip()
    return " ".join(token for token in normalized.split() if token)


def looks_low_quality(title: str, url: str) -> bool:
    normalized_title = clean_text(title).lower()
    parsed = urlparse(url)
    if len(normalized_title) < 3:
        return True
    if normalized_title in {"cache", "redirect", "javascript required"}:
        return True
    if parsed.netloc.lower() in {"github.com", "www.github.com"} and parsed.path.strip("/") == "":
        return True
    if parsed.netloc.lower() in {"www.google.com", "google.com", "www.bing.com", "bing.com"} and parsed.path.strip("/") in {"", "search"}:
        return True
    if normalized_title in {
        "github change is constant github keeps you ahead",
        "github · change is constant. github keeps you ahead.",
    }:
        return True
    return "/redirect" in url.lower()


def strip_tracking_params(url: str) -> str:
    parsed = urlparse(url)
    filtered = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key in TRACKER_KEYS or key.startswith(TRACKER_PREFIXES):
            continue
        filtered.append((key, value))
    return urlunparse((parsed.scheme.lower() or "https", parsed.netloc.lower(), parsed.path or "/", "", urlencode(filtered, doseq=True), ""))


def has_meaningful_overlap(query: str, *fields: str) -> bool:
    query_tokens = set(meaningful_query_tokens(query))
    if not query_tokens:
        return True
    doc_tokens: set[str] = set()
    for field in fields:
        doc_tokens.update(_tokenize(field))
    return bool(query_tokens & doc_tokens)


def meaningful_query_tokens(text: str) -> list[str]:
    tokens = [token for token in _tokenize(text) if token not in STOPWORDS]
    return tokens or _tokenize(text)


def score_hit(query: str, hit: RawSearchHit, *, category: SearchCategory) -> float:
    query_tokens = meaningful_query_tokens(query)
    title_overlap = _overlap(query_tokens, _tokenize(hit.title))
    snippet_overlap = _overlap(query_tokens, _tokenize(hit.snippet))
    consensus_bonus = min(0.25, 0.06 * max(0, len(hit.engines) - 1))
    source_bonus = SOURCE_PRIORS.get(hit.engine, 0.0)
    freshness_bonus = 0.0
    if category == "news" and hit.published_at is not None:
        age_hours = max(0.0, (datetime.now(timezone.utc) - hit.published_at.astimezone(timezone.utc)).total_seconds() / 3600)
        freshness_bonus = max(0.0, 0.15 - min(0.15, age_hours / (24 * 10)))
    category_bonus = 0.0
    if category == "academic" and hit.source_type == "academic":
        category_bonus = 0.08
    if category == "code" and hit.source_type == "code":
        category_bonus = 0.08
    if category == "reference" and urlparse(hit.canonical_url or hit.url).netloc.endswith("wikipedia.org"):
        category_bonus = 0.08
    length_bonus = min(0.06, math.log(len(_tokenize(hit.title + " " + hit.snippet)) + 1, 15) * 0.06)
    return round((title_overlap * 0.45) + (snippet_overlap * 0.22) + consensus_bonus + source_bonus + freshness_bonus + category_bonus + length_bonus, 4)


def choose_user_agent(default_user_agent: str, rotate: bool) -> str:
    if not rotate:
        return default_user_agent
    return random.choice(USER_AGENTS)


def build_async_client(
    *,
    timeout_seconds: float,
    follow_redirects: bool,
    user_agent: str,
    accept_language: str,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=follow_redirects,
        headers={
            "User-Agent": user_agent,
            "Accept-Language": accept_language,
            "DNT": "1",
        },
        cookies={},
    )


def _normalize_relative_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _decode_bing_redirect_target(value: str) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return ""
    if candidate.startswith(("http://", "https://", "//")):
        return _normalize_relative_url(candidate)
    if candidate.startswith("a1"):
        candidate = candidate[2:]
    candidate = candidate.replace("-", "+").replace("_", "/")
    padding = "=" * (-len(candidate) % 4)
    for decoder in (b64decode, urlsafe_b64decode):
        try:
            decoded = decoder(candidate + padding).decode("utf-8", errors="ignore").strip()
        except Exception:
            continue
        if decoded.startswith(("http://", "https://", "//")):
            return _normalize_relative_url(decoded)
    return ""


def _tokenize(text: str) -> list[str]:
    raw_tokens = TOKEN_RE.findall((text or "").lower())
    normalized: list[str] = []
    for token in raw_tokens:
        normalized.append(token)
        normalized.extend(TOKEN_ALIASES.get(token, []))
    return normalized


def _overlap(query_tokens: list[str], doc_tokens: list[str]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    query_counts = Counter(query_tokens)
    doc_counts = Counter(doc_tokens)
    overlap = sum(min(doc_counts[token], count) for token, count in query_counts.items())
    return overlap / len(query_tokens)
