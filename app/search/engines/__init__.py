from app.search.engines.arxiv import ArxivEngine
from app.search.engines.base import SearchEngine
from app.search.engines.bing_web import BingWebEngine
from app.search.engines.brave_web import BraveWebEngine
from app.search.engines.duckduckgo_lite import DuckDuckGoLiteEngine
from app.search.engines.github import GitHubEngine
from app.search.engines.google_news_rss import GoogleNewsRssEngine
from app.search.engines.google_web import GoogleWebEngine
from app.search.engines.stackoverflow import StackOverflowEngine
from app.search.engines.wikipedia import WikipediaEngine


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
