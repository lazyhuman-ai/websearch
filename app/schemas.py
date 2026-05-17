from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class SearchResult(BaseModel):
    source_id: str
    title: str
    url: HttpUrl
    snippet: str = ""
    engine: str = "searxng"


class WebDocument(BaseModel):
    source_id: str
    title: str
    url: HttpUrl
    snippet: str = ""
    engine: str = "searxng"
    content: str = ""
    success: bool = False
    error: str | None = None
    score: float = 0.0


class ResearchPlan(BaseModel):
    original_question: str
    rewritten_question: str
    needs_freshness: bool = False
    date_context: str | None = None
    search_queries: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ResearchPlanToolArgs(BaseModel):
    rewritten_question: str
    needs_freshness: bool = False
    date_context: str | None = None
    search_queries: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ResearchSource(BaseModel):
    source_id: str
    title: str
    url: HttpUrl
    score: float = 0.0


class DeepResearchMetadata(BaseModel):
    search_provider: str = "searxng"
    num_search_results: int = 0
    num_documents_read: int = 0
    num_sources_used: int = 0
    tool_calls: int = 0
    markdown_path: str | None = None
    plan_queries: list[str] = Field(default_factory=list)
    visited_urls: list[HttpUrl] = Field(default_factory=list)


class DeepResearchRequest(BaseModel):
    question: str = Field(..., min_length=3)
    save_markdown: bool = True
    output_dir: str = "research_outputs"


class DeepResearchResponse(BaseModel):
    question: str
    plan: ResearchPlan
    answer: str
    markdown: str
    sources: list[ResearchSource]
    metadata: DeepResearchMetadata


class ToolExecutionRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResponse(BaseModel):
    name: str
    result: dict[str, Any]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str | None = None
    parse_error: str | None = None


class ChatResponse(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    raw: dict[str, Any] | None = None
