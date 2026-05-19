# Websearch

[English](./README.md) | [简体中文](./README_zh.md)

[Project Origin](#project-origin) | [Current Status](#current-status) | [Core Architecture](#core-architecture) | [Roadmap](#roadmap) | [Quick Start](#quick-start) | [Configuration](#configuration) | [Known Limitations](#known-limitations)

Lightweight multi-engine web search infrastructure for agents.

This project is intended to provide a lightweight, deployment-free, modifiable `websearch tool backend` for people building their own Agent Framework, Tool Runtime, Orchestrator, or Research Stack.

It only includes the necessary pieces:

- accept a search request
- call multiple upstream search engines in parallel
- normalize heterogeneous results into one schema
- deduplicate, rank, and clean results
- return results in a format that agents can consume more easily
- optionally attach URL resolution and content extraction when needed

## Project Origin

This project grew out of a practical problem:

Most agent systems need a web search tool, but the common options all come with tradeoffs:

- using provider APIs for web search is convenient, but often opaque, and costs time and money
- browser automation is the most powerful option, but it is complex and slow
- integrating a single search engine is simple, but fragile and limiting

That is where this project comes from:

Build an open, modifiable, inspectable web search backend that can serve as an alternative tool layer for agents.

It is a good fit for:

- a custom websearch tool inside an agent framework
- a search backend behind your own tool API
- a lightweight, deployment-free alternative that avoids hard dependence on a commercial search interface

## Current Status

This project is still rough and early-stage.
It is already usable as an experimental backend and a starting point for custom agent tooling, but it is still far from being a finished and robust web search system.

There are still many obvious rough edges:

- upstream search engine markup changes can break parsing
- some extraction paths are still brittle
- ranking quality is only a baseline
- planner rules are not stable enough yet
- LLM planner compatibility across providers is still incomplete
- support for custom configuration is still limited

## Design Goals

- Agent First
  Outputs are optimized for LLM and tool consumption rather than only for human reading.
- Multi-Engine by Default
  The system should not be tightly bound to a single search provider.
- Transparent
  Planner behavior, used engines, failures, and ranking logic should be inspectable.
- Lightweight
  The implementation should stay small, easy to fork, and easy to embed.
- Replaceable
  Planner logic, engine adapters, and extraction logic should be swappable independently.

## What It Does

- concurrent search across multiple engines
- category-aware routing such as `general`, `news`, `reference`, `academic`, and `code`
- YAML-based engine group configuration
- multiple request header profiles per engine
- unified result schema across different sources
- deduplication by URL and title signature
- a minimal but useful ranking layer
- optional URL resolution and readable content extraction
- structured logs for debugging and offline evaluation

Current built-in upstream search engines include:

- `google_web`
- `bing_web`
- `brave_web`
- `duckduckgo_lite`
- `wikipedia`
- `arxiv`
- `stackoverflow`
- `github`
- `google_news_rss`

## Core Architecture

The main flow can be summarized as:

`SearchRequest -> planner -> engine fanout -> parse -> normalize -> dedupe -> rank -> SearchResponse`

Main components:

- `SearchRequest`
  Describes one search request, including query, category, language, site, time range, and engine request limits.
- `RulePlanner` / `LLMPlanner`
  Decide which engines should be used and optionally rewrite the query.
- `SearchEngine`
  One adapter per upstream source.
- `SearchClient`
  Handles fanout, aggregation, fallback, ranking, URL resolution, and response formatting.
- `url_tools`
  Handles URL resolution and content extraction.

## Roadmap

This project will continue to be improved into a backend that is more suitable for agent use.

### More Search Backends

- add more upstream search backends and provider adapters
- make backend abstraction cleaner and easier to swap
- support more hosted and provider-native backends beyond HTML-based engines
- provide more specialized source coverage for news, docs, code, and academic content

### More Robust Web Search

- make HTML parsing more resilient to upstream layout changes
- improve redirect unwrapping and wrapper-link recovery
- better handle throttling, challenge pages, soft bans, and regional interstitials
- design clearer retry and degradation strategies for different backends
- provide better fallback behavior when content extraction fails

### Ranking and Result Quality

- keep improving ranking instead of stopping at the current heuristic baseline
- add better category-specific source priors
- introduce domain-level trust and quality signals
- improve freshness ranking for news queries
- improve aggregation and consensus handling across engines
- suppress low-quality outputs such as video noise, wrapper pages, and near-duplicates

### Planner

- add more rule-based planner rules for common agent search patterns
- improve query rewriting for ambiguous, factual, temporal, and site-specific requests
- improve LLM planner compatibility across providers and response formats
- provide more stable fallback behavior when LLM planning is unavailable
- make planner decisions easier to inspect, record, and evaluate offline

### Agent Integration

- expose cleaner `web_search` / `web_extract` tool interfaces
- add integration examples for common agent runtimes
- separate search, fetch, and browser escalation paths more clearly
- provide better structured telemetry and debugging information

### Evaluation and Regression

- add repeatable regression tests for search quality
- build benchmark query sets organized by category
- add result-quality inspection and failure categorization tooling
- continuously track planner behavior, engine health, and extraction quality over time

## Repository Layout

```text
app/
  config.py
  search/
    core.py
    planner.py
    llm_planner.py
    engine_config.py
    url_tools.py
    search_engines.yaml
    engines/
scripts/
  search_web.py
  batch_test_search.py
```

## Installation

```bash
pip install -r requirements.txt
```

## Quick Start

Basic usage:

```bash
python3 scripts/search_web.py "what is CRDT" --pretty
```

News search:

```bash
python3 scripts/search_web.py "today's news" --category news --pretty
```

Code-oriented search:

```bash
python3 scripts/search_web.py "GitHub Actions permission denied shell script" --category code --pretty
```

Site-restricted search:

```bash
python3 scripts/search_web.py "asyncio taskgroup" --site docs.python.org --pretty
```

With readable content extraction:

```bash
python3 scripts/search_web.py "OpenAI API responses" --read --pretty
```

Batch smoke test:

```bash
python3 scripts/batch_test_search.py --pretty
```

## Configuration

The default configuration file is [app/search/search_engines.yaml](./app/search/search_engines.yaml).

It mainly controls three things:

- engine groups
- disabled engines
- header profiles for each engine

Example:

```yaml
groups:
  general:
    - bing_web
    - duckduckgo_lite
    - google_web
    - brave_web

engine_headers:
  google_web:
    - User-Agent: Mozilla/5.0 (...)
      Accept-Language: en-US,en;q=0.9
    - User-Agent: Mozilla/5.0 (...)
      Accept-Language: en-GB,en;q=0.8
```

Common CLI parameters:

- `--category`
- `--language`
- `--site`
- `--time-range`
- `--max-results`
  How many results to request per upstream search request, not the final result cap.
- `--max-engine-requests`
  The maximum number of paginated requests to send to each engine.
- `--engine-config`
- `--resolve-urls` / `--no-resolve-urls`
- `--include-url-content` / `--no-include-url-content`
- `--read`

## Output Shape

The CLI returns JSON with fields such as:

- `query`
- `request`
- `used_engines`
- `results`
- `planner`
- `engine_health`
- `engine_failures`

When `--read` is enabled, the output also includes:

- `documents`

## Logging

The scripts write two kinds of logs:

- raw JSON logs
- clean logs
  only URL plus readable extracted content, with fallback to `title + snippet` when body content is empty

Default paths:

- `logs/search_web.log`
- `logs/search_web.clean.log`
- `logs/batch_test_search.log`
- `logs/batch_test_search.clean.log`

## Known Limitations

- HTML-based search engines are sensitive to markup changes
- some engines may trigger challenges, `429`, geo restrictions, or unexpected redirects
- Google News often returns wrapper links instead of publisher-direct URLs
- readable content extraction is best-effort and is not equivalent to browser rendering
- some pages are naturally better handled by a browser tool than by HTTP fetch plus extraction
- this project prioritizes controllability and inspectability over perfect recall

## When This Project Is a Good Fit

Good fit:

- you are building your own agent framework
- you want a replaceable, self-hostable websearch backend
- you need to debug why a result was returned
- you want to study query routing, engine selection, and ranking

Not a good fit:

- you only need browser-level page interaction
- you only want the easiest possible vendor-native search
- you mainly deal with websites that require login or frontend rendering

## License

If the repository already includes a license, that file is authoritative. If you plan to open-source this project publicly, you should add an explicit license file.

## Chinese README

For the Chinese version, see [README_zh.md](/Users/tongbu/lazyhuman-ai/websearch/README_zh.md).
