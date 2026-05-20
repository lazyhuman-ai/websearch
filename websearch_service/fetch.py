from __future__ import annotations

from websearch_service.config import Settings
from websearch_service.search.normalize import clean_text
from websearch_service.search.url_tools import get_url
from websearch_service.schemas import FetchMetadata, FetchResult


def fetch_url(url: str, *, settings: Settings | None = None) -> FetchResult:
    parsed = get_url(
        url,
        resolve=True,
        markdown=False,
        include_content=True,
        settings=settings,
    )
    text = parsed.content_text or parsed.content_markdown
    excerpt = parsed.content_excerpt or clean_text(text)[:240].rstrip(" ,;:|-")
    return FetchResult(
        url=parsed.final_url or parsed.resolved_url or parsed.normalized_url or parsed.input_url,
        title=parsed.title,
        text=text,
        excerpt=excerpt,
        metadata=FetchMetadata(
            author=None,
            published_at=None,
            domain=parsed.domain,
        ),
    )
