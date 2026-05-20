from __future__ import annotations

from dataclasses import asdict, dataclass, field
from dataclasses import replace
from datetime import datetime
from typing import Literal


SearchCategory = Literal["auto", "general", "news", "reference", "academic", "code"]
TimeRange = Literal["any", "day", "week", "month", "year"]


@dataclass(slots=True)
class SearchRequest:
    query: str
    category: SearchCategory = "auto"
    language: str = "en-US"
    page: int = 1
    time_range: TimeRange = "any"
    max_results: int = 5
    max_engine_requests: int = 1
    enabled_engines: list[str] = field(default_factory=list)
    site: str | None = None
    resolve_urls: bool = True
    include_url_content: bool = True
    planner_query: str | None = None

    def effective_query(self) -> str:
        base_query = (self.planner_query or self.query).strip()
        if self.site and f"site:{self.site}" not in base_query:
            return f"{base_query} site:{self.site}".strip()
        return base_query

    def for_engine_request(self, request_index: int) -> SearchRequest:
        return replace(self, page=max(1, self.page + request_index))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ParsedUrlResult:
    input_url: str
    resolved_url: str = ""
    final_url: str = ""
    normalized_url: str = ""
    domain: str = ""
    path: str = "/"
    query: dict[str, str] = field(default_factory=dict)
    title: str = ""
    content_markdown: str = ""
    content_text: str = ""
    content_excerpt: str = ""
    content_type: str = ""
    http_status: int | None = None
    fetch_succeeded: bool = False
    extractor: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    engine: str = ""
    engines: list[str] = field(default_factory=list)
    source_type: str = "web"
    published_at: str | None = None
    score: float = 0.0
    parsed_url: ParsedUrlResult | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        if self.parsed_url is not None:
            payload["parsed_url"] = self.parsed_url.to_dict()
        return payload


@dataclass(slots=True)
class SearchResponse:
    query: str
    request: dict[str, object]
    used_engines: list[str]
    results: list[SearchResult]
    planner: dict[str, object] = field(default_factory=dict)
    engine_health: dict[str, object] = field(default_factory=dict)
    engine_failures: dict[str, str] = field(default_factory=dict)
    engine_diagnostics: dict[str, dict[str, object]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "request": self.request,
            "used_engines": self.used_engines,
            "results": [item.to_dict() for item in self.results],
            "planner": self.planner,
            "engine_health": self.engine_health,
            "engine_failures": self.engine_failures,
            "engine_diagnostics": self.engine_diagnostics,
        }


@dataclass(slots=True)
class WebDocument:
    title: str
    url: str
    engine: str = ""
    snippet: str = ""
    content_markdown: str = ""
    content_text: str = ""
    success: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RawSearchHit:
    title: str
    url: str
    snippet: str = ""
    engine: str = ""
    engines: list[str] = field(default_factory=list)
    published_at: datetime | None = None
    canonical_url: str = ""
    title_signature: str = ""
    source_type: str = "web"
    score: float = 0.0


class SearchAdapterError(RuntimeError):
    """Raised when one upstream adapter fails."""
