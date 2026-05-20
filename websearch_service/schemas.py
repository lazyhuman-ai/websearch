from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


Freshness = Literal["any", "day", "week", "month", "year"]


@dataclass(slots=True)
class SearchResultItem:
    title: str
    url: str
    snippet: str
    engine: str
    rank: int
    published_at: str | None = None
    domain: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class FetchMetadata:
    author: str | None = None
    published_at: str | None = None
    domain: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class FetchResult:
    url: str
    title: str
    text: str
    excerpt: str
    metadata: FetchMetadata = field(default_factory=FetchMetadata)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["metadata"] = self.metadata.to_dict()
        return payload
