from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    default_language: str = Field(default="en-US", validation_alias=AliasChoices("SEARCH_DEFAULT_LANGUAGE"))
    default_category: str = Field(default="general", validation_alias=AliasChoices("SEARCH_DEFAULT_CATEGORY"))
    default_time_range: str = Field(default="any", validation_alias=AliasChoices("SEARCH_DEFAULT_TIME_RANGE"))
    max_results_per_query: int = Field(default=10, validation_alias=AliasChoices("MAX_RESULTS_PER_QUERY"))
    request_timeout_seconds: float = Field(default=12.0, validation_alias=AliasChoices("REQUEST_TIMEOUT_SECONDS"))
    search_engine_timeout_seconds: float = Field(default=8.0, validation_alias=AliasChoices("SEARCH_ENGINE_TIMEOUT_SECONDS"))
    search_total_timeout_seconds: float = Field(default=15.0, validation_alias=AliasChoices("SEARCH_TOTAL_TIMEOUT_SECONDS"))
    search_ban_seconds: float = Field(default=120.0, validation_alias=AliasChoices("SEARCH_BAN_SECONDS"))
    search_challenge_ban_seconds: float = Field(default=900.0, validation_alias=AliasChoices("SEARCH_CHALLENGE_BAN_SECONDS"))
    search_rate_limit_ban_seconds: float = Field(default=600.0, validation_alias=AliasChoices("SEARCH_RATE_LIMIT_BAN_SECONDS"))
    search_engine_retry_count: int = Field(default=1, validation_alias=AliasChoices("SEARCH_ENGINE_RETRY_COUNT"))
    search_user_agent_rotation: bool = Field(default=True, validation_alias=AliasChoices("SEARCH_USER_AGENT_ROTATION"))
    search_strip_trackers: bool = Field(default=True, validation_alias=AliasChoices("SEARCH_STRIP_TRACKERS"))
    search_read_results: int = Field(default=3, validation_alias=AliasChoices("SEARCH_READ_RESULTS"))
    cache_ttl_seconds: int = Field(default=900, validation_alias=AliasChoices("CACHE_TTL_SECONDS"))
    max_document_chars: int = Field(default=12000, validation_alias=AliasChoices("MAX_DOCUMENT_CHARS"))
    search_engine_config_path: str = Field(
        default=str(Path("websearch_service/search/search_engines.yaml")),
        validation_alias=AliasChoices("SEARCH_ENGINE_CONFIG_PATH"),
    )
    llm_planner_enabled: bool = Field(default=True, validation_alias=AliasChoices("LLM_PLANNER_ENABLED"))
    llm_base_url: str = Field(default="https://api.openai.com/v1", validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"))
    llm_api_key: str = Field(default="", validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    llm_model: str = Field(default="gpt-4.1-mini", validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"))
    llm_timeout_seconds: float = Field(default=20.0, validation_alias=AliasChoices("LLM_TIMEOUT_SECONDS"))
    user_agent: str = Field(default="websearch-minimal/1.0 (+https://localhost)", validation_alias=AliasChoices("USER_AGENT"))
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
