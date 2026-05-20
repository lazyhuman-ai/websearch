from websearch_service.engines.arxiv import ArxivEngine
from websearch_service.engines.base import SearchEngine
from websearch_service.engines.bing_web import BingWebEngine
from websearch_service.engines.brave_web import BraveWebEngine
from websearch_service.engines.duckduckgo_lite import DuckDuckGoLiteEngine
from websearch_service.engines.github import GitHubEngine
from websearch_service.engines.google_news_rss import GoogleNewsRssEngine
from websearch_service.engines.google_web import GoogleWebEngine
from websearch_service.engines.stackoverflow import StackOverflowEngine
from websearch_service.engines.wikipedia import WikipediaEngine


def build_engine_registry() -> dict[str, SearchEngine]:
    engines = [
        GoogleWebEngine(),
        BingWebEngine(),
        BraveWebEngine(),
        DuckDuckGoLiteEngine(),
        WikipediaEngine(),
        ArxivEngine(),
        StackOverflowEngine(),
        GitHubEngine(),
        GoogleNewsRssEngine(),
    ]
    return {engine.name: engine for engine in engines}
