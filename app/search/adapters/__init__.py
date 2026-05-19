from app.search.adapters.base import SearchAdapter
from app.search.adapters.providers import (
    ArxivAdapter,
    BingWebAdapter,
    BraveWebAdapter,
    DuckDuckGoLiteAdapter,
    GitHubAdapter,
    GoogleNewsRssAdapter,
    GoogleWebAdapter,
    StackOverflowAdapter,
    WikipediaAdapter,
)


def build_adapter_registry() -> dict[str, SearchAdapter]:
    adapters = [
        GoogleWebAdapter(),
        BingWebAdapter(),
        BraveWebAdapter(),
        DuckDuckGoLiteAdapter(),
        WikipediaAdapter(),
        ArxivAdapter(),
        StackOverflowAdapter(),
        GitHubAdapter(),
        GoogleNewsRssAdapter(),
    ]
    return {adapter.name: adapter for adapter in adapters}
