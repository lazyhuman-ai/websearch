from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.search.types import RawSearchHit, SearchCategory


TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
SOURCE_PRIORS = {
    "wikipedia": 0.08,
    "arxiv": 0.1,
    "github": 0.07,
    "stackoverflow": 0.08,
    "google_news_rss": 0.06,
}


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def _overlap(query_tokens: list[str], doc_tokens: list[str]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    query_counts = Counter(query_tokens)
    doc_counts = Counter(doc_tokens)
    overlap = sum(min(doc_counts[token], count) for token, count in query_counts.items())
    return overlap / len(query_tokens)


def score_hit(query: str, hit: RawSearchHit, *, category: SearchCategory) -> float:
    query_tokens = _tokenize(query)
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
