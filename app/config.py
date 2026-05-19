from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


class Settings(BaseSettings):
    default_language: str = Field(default="en-US", validation_alias=AliasChoices("SEARCH_DEFAULT_LANGUAGE"))
    default_category: str = Field(default="general", validation_alias=AliasChoices("SEARCH_DEFAULT_CATEGORY"))
    default_time_range: str = Field(default="any", validation_alias=AliasChoices("SEARCH_DEFAULT_TIME_RANGE"))
    search_max_results: int = Field(default=5, validation_alias=AliasChoices("SEARCH_MAX_RESULTS"))
    max_results_per_query: int = Field(default=10, validation_alias=AliasChoices("MAX_RESULTS_PER_QUERY"))
    request_timeout_seconds: float = Field(default=12.0, validation_alias=AliasChoices("REQUEST_TIMEOUT_SECONDS"))
    search_engine_timeout_seconds: float = Field(default=8.0, validation_alias=AliasChoices("SEARCH_ENGINE_TIMEOUT_SECONDS"))
    search_total_timeout_seconds: float = Field(default=15.0, validation_alias=AliasChoices("SEARCH_TOTAL_TIMEOUT_SECONDS"))
    search_ban_seconds: float = Field(default=120.0, validation_alias=AliasChoices("SEARCH_BAN_SECONDS"))
    search_user_agent_rotation: bool = Field(default=True, validation_alias=AliasChoices("SEARCH_USER_AGENT_ROTATION"))
    search_strip_trackers: bool = Field(default=True, validation_alias=AliasChoices("SEARCH_STRIP_TRACKERS"))
    search_read_results: int = Field(default=3, validation_alias=AliasChoices("SEARCH_READ_RESULTS"))
    request_interval_seconds: float = Field(default=1.0, validation_alias=AliasChoices("REQUEST_INTERVAL_SECONDS"))
    cache_ttl_seconds: int = Field(default=900, validation_alias=AliasChoices("CACHE_TTL_SECONDS"))
    max_document_chars: int = Field(default=12000, validation_alias=AliasChoices("MAX_DOCUMENT_CHARS"))
    user_agent: str = Field(default="websearch-minimal/1.0 (+https://localhost)", validation_alias=AliasChoices("USER_AGENT"))
    general_engines: list[str] = Field(
        default_factory=lambda: ["google_web", "bing_web", "brave_web", "duckduckgo_lite"],
        validation_alias=AliasChoices("SEARCH_GENERAL_ENGINES"),
    )
    news_engines: list[str] = Field(
        default_factory=lambda: ["google_web", "bing_web", "google_news_rss", "duckduckgo_lite"],
        validation_alias=AliasChoices("SEARCH_NEWS_ENGINES"),
    )
    reference_engines: list[str] = Field(
        default_factory=lambda: ["google_web", "bing_web", "duckduckgo_lite", "wikipedia"],
        validation_alias=AliasChoices("SEARCH_REFERENCE_ENGINES"),
    )
    academic_engines: list[str] = Field(
        default_factory=lambda: ["google_web", "bing_web", "arxiv"],
        validation_alias=AliasChoices("SEARCH_ACADEMIC_ENGINES"),
    )
    code_engines: list[str] = Field(
        default_factory=lambda: ["google_web", "bing_web", "duckduckgo_lite", "stackoverflow", "github"],
        validation_alias=AliasChoices("SEARCH_CODE_ENGINES"),
    )
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    @field_validator(
        "general_engines",
        "news_engines",
        "reference_engines",
        "academic_engines",
        "code_engines",
        mode="before",
    )
    @classmethod
    def parse_engine_lists(cls, value: Any) -> Any:
        return _csv_list(value) or value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
