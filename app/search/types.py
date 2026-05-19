from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    enabled_engines: list[str] = field(default_factory=list)
    site: str | None = None

    def effective_query(self) -> str:
        if self.site and f"site:{self.site}" not in self.query:
            return f"{self.query} site:{self.site}".strip()
        return self.query.strip()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    engine: str = ""
    engines: list[str] = field(default_factory=list)
    published_at: str | None = None
    score: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class SearchResponse:
    query: str
    request: dict[str, object]
    used_engines: list[str]
    results: list[SearchResult]
    engine_failures: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "request": self.request,
            "used_engines": self.used_engines,
            "results": [item.to_dict() for item in self.results],
            "engine_failures": self.engine_failures,
        }


@dataclass(slots=True)
class WebDocument:
    title: str
    url: str
    engine: str = ""
    snippet: str = ""
    content: str = ""
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
