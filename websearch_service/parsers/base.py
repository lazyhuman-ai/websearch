from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from websearch_service.types import RawSearchHit, SearchRequest


class SearchResultParser(ABC):
    @abstractmethod
    def parse(self, response: httpx.Response, request: SearchRequest) -> list[RawSearchHit]:
        raise NotImplementedError
