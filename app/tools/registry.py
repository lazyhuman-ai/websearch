from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import AliasChoices, BaseModel, Field, ValidationError, model_validator

from app.tools.web import WebSearchClient


class ToolExecutionError(Exception):
    pass


class UnknownToolError(ToolExecutionError):
    pass


class InvalidToolArgumentsError(ToolExecutionError):
    pass


class SearchWebArgs(BaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=5)


class ReadPageInput(BaseModel):
    source_id: str = ""
    url: str = Field(
        validation_alias=AliasChoices("url", "link", "href", "uri", "website", "webpage_url", "page_url"),
    )
    title: str = ""
    snippet: str = ""
    engine: str = "searxng"

    @model_validator(mode="before")
    @classmethod
    def normalize_input(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"url": data}
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if not normalized.get("source_id"):
            normalized["source_id"] = "AUTO"
        return normalized


class ReadWebpagesArgs(BaseModel):
    pages: list[ReadPageInput] = Field(min_length=1, max_length=10)

    @model_validator(mode="before")
    @classmethod
    def normalize_pages(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        pages = data.get("pages")
        if not isinstance(pages, list):
            return data
        normalized_pages: list[Any] = []
        for index, item in enumerate(pages, start=1):
            if isinstance(item, str):
                normalized_pages.append({"source_id": f"S{index}", "url": item})
                continue
            if isinstance(item, dict):
                candidate = dict(item)
                if not candidate.get("source_id"):
                    candidate["source_id"] = f"S{index}"
                normalized_pages.append(candidate)
                continue
            normalized_pages.append(item)
        return {"pages": normalized_pages}


class SearchAndReadArgs(BaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=3, ge=1, le=5)


class FinishResearchArgs(BaseModel):
    summary: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)


@dataclass
class ToolDefinition:
    name: str
    description: str
    schema_model: type[BaseModel]
    handler: Callable[[BaseModel], dict[str, Any]]

    @property
    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema_model.model_json_schema(),
            },
        }

    def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            validated = self.schema_model.model_validate(arguments)
        except ValidationError as exc:
            raise InvalidToolArgumentsError(f"Invalid arguments for tool {self.name}: {exc}") from exc
        return self.handler(validated)


class ToolRegistry:
    def __init__(self) -> None:
        self.web = WebSearchClient()
        self._tools = {
            "search_web": ToolDefinition(
                name="search_web",
                description="Search the web and return titles, URLs, snippets, and source IDs.",
                schema_model=SearchWebArgs,
                handler=self._search_web,
            ),
            "read_webpages": ToolDefinition(
                name="read_webpages",
                description=(
                    "Fetch webpages by URL and return extracted markdown-like readable content. "
                    "For each page include at least a URL. Prefer reusing source_id/title from search results."
                ),
                schema_model=ReadWebpagesArgs,
                handler=self._read_webpages,
            ),
            "search_web_and_read": ToolDefinition(
                name="search_web_and_read",
                description="Search the web, then read the top results and return both URLs and extracted content.",
                schema_model=SearchAndReadArgs,
                handler=self._search_web_and_read,
            ),
            "finish_research": ToolDefinition(
                name="finish_research",
                description="Call this only when enough evidence has been gathered and you are ready to write the final answer.",
                schema_model=FinishResearchArgs,
                handler=self._finish_research,
            ),
        }

    def list_openai_schemas(self) -> list[dict[str, Any]]:
        return [tool.openai_schema for tool in self._tools.values()]

    def list_descriptions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.schema_model.model_json_schema(),
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownToolError(f"Unknown tool: {name}")
        return tool.execute(arguments)

    def _search_web(self, arguments: SearchWebArgs) -> dict[str, Any]:
        results = self.web.search(arguments.query, max_results=arguments.max_results)
        return {
            "query": arguments.query,
            "results": [item.model_dump(mode="json") for item in results],
        }

    def _read_webpages(self, arguments: ReadWebpagesArgs) -> dict[str, Any]:
        documents = self.web.read_pages([item.model_dump() for item in arguments.pages])
        return {
            "documents": [item.model_dump(mode="json") for item in documents],
        }

    def _search_web_and_read(self, arguments: SearchAndReadArgs) -> dict[str, Any]:
        results, documents = self.web.search_and_read(arguments.query, max_results=arguments.max_results)
        return {
            "query": arguments.query,
            "results": [item.model_dump(mode="json") for item in results],
            "documents": [item.model_dump(mode="json") for item in documents],
        }

    def _finish_research(self, arguments: FinishResearchArgs) -> dict[str, Any]:
        return arguments.model_dump()


def dump_tool_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
