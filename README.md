# Websearch

[English](./README.md) | [简体中文](./README_zh.md)

Lightweight multi-engine web search and content fetch backend for agent tool calls.

Websearch gives agents two simple primitives:

- `web_search(query, count, language, freshness)` returns normalized search results.
- `web_fetch(url)` resolves a URL and returns readable text plus metadata.

It is built for local, inspectable, and easily modifiable agent infrastructure. Search requests can fan out to multiple engines, use category-aware routing, normalize provider-specific results, rank them, and optionally fetch article text.

## Features

- Multi-engine search: Bing, DuckDuckGo Lite, Google Web, Brave, Google News RSS, GitHub, arXiv, Wikipedia, StackOverflow.
- Agent-friendly schema: stable `title`, `url`, `snippet`, `engine`, `rank`, `published_at`, `domain`, `score`.
- Clean fetch output: `url`, `title`, `text`, `excerpt`, and metadata.
- Transparent diagnostics: used engines, failed engines, failure reasons, raw hit counts, and health state.
- Simple structure: planner, headers, engines, parsers, collector, aggregator, fetcher.
- No required external search API key for the default HTML/RSS engines.

## Install

```bash
pip install -r requirements.txt
```

## Quick Start

Search:

```bash
python3 scripts/search_web.py "OpenAI latest news" --pretty
```

Search and fetch every returned result:

```bash
python3 scripts/search_web.py "OpenAI latest news" --fetch-all --fetch-limit 5 --pretty
```

Fetch one URL directly:

```bash
python3 scripts/search_web.py "OpenAI latest news" --fetch-url https://openai.com/news/ --pretty
```

Run smoke tests:

```bash
python3 scripts/batch_test_search.py --pretty
```

## News Example

Command:

```bash
python3 scripts/search_web.py "latest AI infrastructure news" --freshness week --fetch-all --fetch-limit 2 --pretty
```

Example output shape:

```json
{
  "query": "latest AI infrastructure news",
  "freshness": "week",
  "providers": ["bing", "duckduckgo", "google", "brave", "google_news"],
  "used_engines": ["bing_web", "duckduckgo_lite", "google_web", "brave_web", "google_news_rss"],
  "failed_engines": ["google_web", "brave_web"],
  "engine_failures": {
    "google_web": "google_web parse_error=google_web blocked_challenge",
    "brave_web": "brave_web http_status=429"
  },
  "results": [
    {
      "title": "Building Community-First AI Infrastructure - The Official Microsoft Blog",
      "url": "https://news.google.com/rss/articles/...",
      "snippet": "Building Community-First AI Infrastructure The Official Microsoft Blog",
      "engine": "google_news_rss",
      "rank": 1,
      "published_at": "2026-01-13T08:00:00+00:00",
      "domain": "news.google.com",
      "score": 0.79
    }
  ],
  "fetched_results": [
    {
      "rank": 1,
      "source_engine": "google_news_rss",
      "source_url": "https://news.google.com/rss/articles/...",
      "fetch": {
        "url": "https://blogs.microsoft.com/...",
        "title": "Building Community-First AI Infrastructure",
        "text": "Cleaned article text...",
        "excerpt": "Short extracted excerpt...",
        "metadata": {
          "domain": "blogs.microsoft.com",
          "http_status": 200,
          "extractor": "trafilatura",
          "error": null
        }
      }
    }
  ]
}
```

Notes:

- Google News wrapper URLs are resolved to publisher URLs during fetch when possible.
- Engine failures are kept in the payload so agents and logs can explain partial results.
- `--fetch-limit 0` means fetch all returned results.

## Python API

```python
from websearch_service import web_fetch, web_search, web_search_payload

results = web_search(
    "latest AI infrastructure news",
    count=0,
    language="en-US",
    freshness="week",
)

article = web_fetch(results[0]["url"])

debug_payload = web_search_payload(
    query="latest AI infrastructure news",
    count=0,
    language="en-US",
    freshness="week",
)
```

## Project Layout

```text
websearch_service/
  search.py        # public search orchestration
  fetch.py         # URL resolution and content extraction
  planner.py       # rule and optional LLM routing
  headers.py       # per-engine request headers
  collect.py       # concurrent engine execution
  aggregate.py     # dedupe, score, rank
  engines/         # one request adapter per provider
  parsers/         # one parser per provider
  types.py         # shared result models
  utils.py         # normalization helpers
scripts/
  search_web.py
  batch_test_search.py
```

## CLI Options

- `--count`: per-engine result count. `0` returns the full aggregated ranked list.
- `--freshness`: `any`, `day`, `week`, `month`, or `year`.
- `--language`: language hint such as `en-US` or `zh-CN`.
- `--providers`: comma-separated provider override, for example `bing,duckduckgo`.
- `--fetch-top`: fetch only the top result.
- `--fetch-all`: fetch every returned result.
- `--fetch-limit`: max URLs to fetch with `--fetch-all`; `0` means all.
- `--log-file` / `--clean-log-file`: raw JSON logs and readable content logs.

## Limitations

- HTML search engines can break when upstream markup changes.
- Some providers may return challenges, `429`, geo blocks, or empty pages.
- HTTP fetch is best-effort and cannot replace full browser rendering.
- Login-only or heavily client-rendered pages should be handled by a browser tool.
- The project prioritizes transparency and hackability over perfect recall.

## License

If the repository includes a license file, that file is authoritative.
