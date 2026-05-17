from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    searxng_base_url: str = Field(
        default="http://127.0.0.1:8080",
        validation_alias=AliasChoices("SEARXNG_BASE_URL"),
    )
    searxng_categories: str = Field(
        default="general,news",
        validation_alias=AliasChoices("SEARXNG_CATEGORIES"),
    )
    search_max_results: int = Field(default=5, validation_alias=AliasChoices("SEARCH_MAX_RESULTS"))
    search_read_results: int = Field(default=3, validation_alias=AliasChoices("SEARCH_READ_RESULTS"))
    rerank_top_k: int = Field(default=5, validation_alias=AliasChoices("RERANK_TOP_K"))
    request_timeout_seconds: float = Field(default=10.0, validation_alias=AliasChoices("REQUEST_TIMEOUT_SECONDS"))
    max_queries_per_task: int = Field(default=3, validation_alias=AliasChoices("MAX_QUERIES_PER_TASK"))
    max_results_per_query: int = Field(default=5, validation_alias=AliasChoices("MAX_RESULTS_PER_QUERY"))
    request_interval_seconds: float = Field(default=2.0, validation_alias=AliasChoices("REQUEST_INTERVAL_SECONDS"))
    max_concurrent_searches: int = Field(default=1, validation_alias=AliasChoices("MAX_CONCURRENT_SEARCHES"))
    cache_ttl_seconds: int = Field(default=3600, validation_alias=AliasChoices("CACHE_TTL_SECONDS"))
    max_document_chars: int = Field(default=12000, validation_alias=AliasChoices("MAX_DOCUMENT_CHARS"))
    agent_max_steps: int = Field(default=6, validation_alias=AliasChoices("AGENT_MAX_STEPS"))
    searxng_auto_start: bool = Field(default=True, validation_alias=AliasChoices("SEARXNG_AUTO_START"))
    searxng_startup_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("SEARXNG_STARTUP_TIMEOUT_SECONDS"),
    )
    searxng_compose_dir: str = Field(
        default=".",
        validation_alias=AliasChoices("SEARXNG_COMPOSE_DIR"),
    )
    searxng_service_name: str = Field(
        default="searxng",
        validation_alias=AliasChoices("SEARXNG_SERVICE_NAME"),
    )
    user_agent: str = Field(
        default="websearch-mvp/0.2 (+https://localhost)",
        validation_alias=AliasChoices("USER_AGENT"),
    )
    llm_provider: str = Field(
        default="mock",
        validation_alias=AliasChoices("LLM_PROVIDER", "OPENAI_PROVIDER"),
    )
    llm_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"),
    )
    llm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
    )
    llm_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"),
    )
    llm_temperature: float = Field(default=0.2, validation_alias=AliasChoices("LLM_TEMPERATURE"))
    llm_max_tokens: int = Field(default=1200, validation_alias=AliasChoices("LLM_MAX_TOKENS"))
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL"))
    log_payload_chars: int = Field(default=1200, validation_alias=AliasChoices("LOG_PAYLOAD_CHARS"))
    log_llm_raw: bool = Field(default=False, validation_alias=AliasChoices("LOG_LLM_RAW"))
    log_dir: str = Field(default="logs", validation_alias=AliasChoices("LOG_DIR"))
    log_file_name: str = Field(default="websearch.log", validation_alias=AliasChoices("LOG_FILE_NAME"))
    log_file_max_bytes: int = Field(default=5_000_000, validation_alias=AliasChoices("LOG_FILE_MAX_BYTES"))
    log_file_backup_count: int = Field(default=3, validation_alias=AliasChoices("LOG_FILE_BACKUP_COUNT"))

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
