from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.search.types import RawSearchHit, SearchAdapterError, SearchRequest


class SearchAdapter(ABC):
    name: str
    source_type: str = "web"

    def supports(self, request: SearchRequest) -> bool:
        return True

    def build_request(self, request: SearchRequest) -> dict[str, object]:
        return {}

    def normalize(self, hit: RawSearchHit) -> RawSearchHit:
        hit.engine = self.name
        if not hit.engines:
            hit.engines = [self.name]
        if not hit.source_type:
            hit.source_type = self.source_type
        return hit

    async def search(self, client: httpx.AsyncClient, request: SearchRequest) -> list[RawSearchHit]:
        try:
            response = await self.fetch(client, request)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SearchAdapterError(f"{self.name} http_status={exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise SearchAdapterError(f"{self.name} http_error={exc}") from exc
        try:
            return [self.normalize(item) for item in self.parse(response, request)]
        except Exception as exc:  # pragma: no cover
            raise SearchAdapterError(f"{self.name} parse_error={exc}") from exc

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
        raise NotImplementedError

    @abstractmethod
    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        raise NotImplementedError
