# Websearch

Lightweight multi-engine web search infrastructure for agents.

This project is built for teams that want a self-hostable, inspectable fallback to vendor-native web search when building their own agent framework, tool layer, or orchestration runtime.

It is not trying to be a browser, a full search engine, or a general crawling platform.
It focuses on one narrow job:

- accept a search request
- route it across multiple upstream search engines
- normalize heterogeneous results into one schema
- deduplicate, rank, and return agent-friendly output
- optionally resolve URLs and extract readable page content

## Why This Project Exists

Most agent stacks eventually need a web search tool, but the common choices have tradeoffs:

- model-native web search is convenient but opaque
- browser automation is powerful but slow and expensive
- direct integration with a single search provider is brittle
- large metasearch systems are flexible but often too heavy for embedding into an agent runtime

This repository exists to fill that gap.

The goal is to provide an open, hackable websearch backend that can be used as:

- a fallback web search tool inside an agent framework
- a replaceable search layer behind your own tool API
- a research sandbox for ranking, routing, and extraction strategies
- a self-hosted alternative when you do not want your framework tightly coupled to one external provider

## Current Status

This is still a rough, early-stage project.

It is useful today as an experimental backend and a starting point for custom agent tooling, but it should not be described as a finished or fully robust web search system.

There are still many rough edges:

- upstream engines can break when markup changes
- some result extraction paths are still brittle
- ranking quality is only a baseline
- planner behavior is still evolving
- provider compatibility for LLM-assisted planning still needs more hardening

If you adopt this project, the right mental model is:

- usable
- inspectable
- hackable
- not finished

That is intentional.
The project was started to make this layer open and editable first, and production-hardening comes later.

## Design Goals

- Agent-first: outputs are structured for LLM and tool use, not just for humans.
- Multi-engine by default: no hard dependency on one provider.
- Transparent: planning, engine usage, failures, and ranking are inspectable.
- Lightweight: simple Python implementation, easy to fork and adapt.
- Replaceable: engines, planner behavior, and extraction logic can be swapped independently.

## What It Does

- Concurrent search across multiple engines
- Query planning by category such as `general`, `news`, `reference`, `academic`, and `code`
- Engine routing with YAML configuration
- Per-engine request header rotation
- Result normalization into a unified schema
- Deduplication by canonical URL and title signature
- Basic ranking with overlap, freshness, source priors, and multi-engine consensus
- Optional URL resolution and readable content extraction
- Structured logs for debugging and offline evaluation

Current upstream adapters include:

- `google_web`
- `bing_web`
- `brave_web`
- `duckduckgo_lite`
- `wikipedia`
- `arxiv`
- `stackoverflow`
- `github`
- `google_news_rss`

## What It Is Not

- not a general-purpose browser automation system
- not a guaranteed high-recall search platform
- not a production crawler for arbitrary web pages
- not a drop-in replacement for all model-native web search products

If a page needs JavaScript execution, login, infinite scroll, or DOM interaction, a browser tool should usually be the next step after this project, not a responsibility of this project itself.

## Project Origin

This project started from a practical engineering problem:

When building agents, web search is often treated as a black box. That is acceptable until you need one of the following:

- explain why a result was returned
- inspect which engines were used
- control routing by query type
- add a custom ranking rule
- swap upstream providers
- keep a self-hosted fallback when a vendor tool is unavailable

This repository was created to make that layer explicit and editable.

The design is influenced by the spirit of projects such as SearXNG and by the tool-oriented ergonomics common in modern agent frameworks, but the implementation is intentionally smaller and easier to embed.

## Roadmap

The roadmap is intentionally pragmatic. The goal is not to become a giant search platform, but to make this backend substantially more useful for real agent systems.

### Search Backends

- Add more upstream search backends and provider adapters
- Support easier backend swapping through a cleaner provider abstraction
- Add optional hosted/provider-native backends alongside HTML-based engines
- Improve source-specific handling for news, docs, code, and academic content

### Robustness

- Make HTML parsing more resilient to upstream layout changes
- Improve redirect unwrapping and wrapper-link recovery
- Improve handling of throttling, challenge pages, soft bans, and regional interstitials
- Add clearer retry and degradation strategies per backend
- Improve extraction fallback behavior when full readable content is unavailable

### Ranking

- Improve result ranking beyond the current baseline heuristics
- Add better source priors by category
- Add domain-level trust and quality signals
- Improve freshness handling for news queries
- Add better aggregation across overlapping results from multiple engines
- Reduce low-quality results such as video noise, wrapper pages, and near-duplicates

### Planner

- Add more rule-based planner coverage for common agent search patterns
- Improve query rewriting for ambiguous, factual, temporal, and site-specific requests
- Improve LLM planner compatibility across providers and response formats
- Add safer fallback behavior when LLM planning is unavailable
- Make planner decisions more inspectable and easier to evaluate offline

### Agent Integration

- Expose a cleaner `web_search` and `web_extract` tool interface
- Add examples for integrating with common agent runtimes
- Separate search, fetch, and browser escalation paths more cleanly
- Add better structured telemetry for tool invocations

### Evaluation

- Add repeatable regression tests for search quality
- Add benchmark query sets by category
- Add result-quality inspection tooling and failure categorization
- Track planner behavior, engine health, and extraction quality over time

## Architecture

The core flow is:

`SearchRequest -> planner -> engine fanout -> parse -> normalize -> dedupe -> rank -> SearchResponse`

Main components:

- `SearchRequest`
  Unified request object for query, category, language, site filter, time range, and engine request limits.
- `RulePlanner` and `LLMPlanner`
  Decide which engines should be used for a request and optionally rewrite the query.
- `SearchEngine`
  Base abstraction implemented once per upstream engine.
- `SearchClient`
  Coordinates fanout, merging, ranking, fallback engines, URL resolution, and response formatting.
- `url_tools`
  Resolves URLs and extracts agent-friendly content from pages.

## Recommended Agent Integration

If you want to use this repository as a tool backend in your own framework, the best pattern is to expose two tools:

1. `web_search`
Search only. Return lightweight ranked candidates.

2. `web_extract`
Fetch and extract readable content only for URLs the agent actually decides to inspect.

This separation keeps search fast and cheap while preserving a path to deeper retrieval when needed.

Recommended `web_search` response fields:

- `title`
- `url`
- `snippet`
- `engine`
- `engines`
- `score`
- `published_at`
- `source_type`

Recommended `web_extract` response fields:

- `final_url`
- `title`
- `content_text`
- `content_markdown`
- `error`

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
python3 scripts/search_web.py "today's nasdaq news" --category news --pretty
```

Code-oriented search:

```bash
python3 scripts/search_web.py "GitHub Actions permission denied shell script" --category code --pretty
```

Site-restricted search:

```bash
python3 scripts/search_web.py "asyncio taskgroup" --site docs.python.org --pretty
```

Content extraction:

```bash
python3 scripts/search_web.py "OpenAI API responses" --read --pretty
```

## Configuration

Default engine configuration lives in [app/search/search_engines.yaml](/Users/tongbu/lazyhuman-ai/websearch/app/search/search_engines.yaml).

It controls:

- engine groups
- disabled engines
- per-engine header profiles

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

## CLI Notes

Key options:

- `--category`
- `--language`
- `--site`
- `--time-range`
- `--max-results`
  Per-engine result count requested from the upstream search engine.
- `--max-engine-requests`
  Maximum paginated requests sent to each engine.
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

The scripts write:

- raw JSON logs
- clean logs with URL plus extracted or fallback-readable content

Default paths:

- `logs/search_web.log`
- `logs/search_web.clean.log`
- `logs/batch_test_search.log`
- `logs/batch_test_search.clean.log`

## Testing

Syntax check:

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m py_compile $(find app scripts -name '*.py')
```

Batch smoke test:

```bash
python3 scripts/batch_test_search.py --pretty
```

## Known Limitations

- HTML search engines are brittle and can break when upstream markup changes.
- Some engines may challenge, throttle, or geo-gate requests.
- Google News often returns wrapper URLs rather than direct publisher links.
- Readable content extraction is best-effort and will not match browser rendering on all sites.
- Some domains are better handled by a browser tool than by HTTP fetch plus extraction.
- This project favors debuggability and controllability over perfect recall.

## When To Use This

Use this project if you want:

- a controllable open-source fallback for agent web search
- a search backend you can embed inside your own framework
- structured search results instead of browser snapshots
- a place to experiment with ranking, routing, and engine selection

Do not use this as your only web tool if your agent needs:

- authenticated browsing
- JavaScript-heavy apps
- interactive page operations
- exact page rendering fidelity

## Contributing

The easiest high-value contributions are:

- adding or fixing engine adapters
- improving result quality and ranking rules
- improving LLM planner compatibility
- improving URL extraction robustness
- adding evaluation datasets and regression tests

## License

See the repository license file if present, or add one before public distribution.

## Chinese README

For the Chinese version, see [README_zh.md](/Users/tongbu/lazyhuman-ai/websearch/README_zh.md).
