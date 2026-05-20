# Websearch

[English](./README.md) | [简体中文](./README_zh.md)

面向 Agent Tool Call 的轻量级多引擎 Web Search 和正文抓取后端。

Websearch 只提供两个核心能力：

- `web_search(query, count, language, freshness)` 返回统一结构的搜索结果。
- `web_fetch(url)` 解析 URL，并返回清洗后的正文和 metadata。

它适合用在自定义 Agent Framework、Tool Runtime、Research Stack 或内部搜索工具中。搜索请求可以并发调用多个 engine，按 query 类型路由，统一不同 provider 的结果结构，排序去重，并在需要时抓取正文。

## 特性

- 多引擎搜索：Bing、DuckDuckGo Lite、Google Web、Brave、Google News RSS、GitHub、arXiv、Wikipedia、StackOverflow。
- Agent 友好结构：稳定返回 `title`、`url`、`snippet`、`engine`、`rank`、`published_at`、`domain`、`score`。
- 清晰的 fetch 输出：`url`、`title`、`text`、`excerpt` 和 metadata。
- 可调试：记录 used engines、failed engines、失败原因、raw hit 数量和 engine health。
- 结构简单：planner、headers、engines、parsers、collector、aggregator、fetcher 分层清楚。
- 默认 HTML/RSS engine 不强制依赖外部搜索 API key。

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

搜索：

```bash
python3 scripts/search_web.py "OpenAI latest news" --pretty
```

搜索后抓取所有返回结果：

```bash
python3 scripts/search_web.py "OpenAI latest news" --fetch-all --fetch-limit 5 --pretty
```

直接抓取一个 URL：

```bash
python3 scripts/search_web.py "OpenAI latest news" --fetch-url https://openai.com/news/ --pretty
```

运行 smoke test：

```bash
python3 scripts/batch_test_search.py --pretty
```

## 新闻示例

命令：

```bash
python3 scripts/search_web.py "latest AI infrastructure news" --freshness week --fetch-all --fetch-limit 2 --pretty
```

返回结构示例：

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
        "text": "清洗后的文章正文...",
        "excerpt": "短摘要...",
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

说明：

- Google News 的包装链接会在 fetch 阶段尽量解析成源站 URL。
- engine 失败不会被吞掉，会保留在 payload 和日志里，方便 Agent 判断结果质量。
- `--fetch-limit 0` 表示抓取所有返回结果。

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

## 项目结构

```text
websearch_service/
  search.py        # search 对外编排入口
  fetch.py         # URL 解析和正文提取
  planner.py       # rule / optional LLM routing
  headers.py       # 每个 engine 的请求头
  collect.py       # 并发调用 engines
  aggregate.py     # 去重、打分、排序
  engines/         # 每个 provider 一个请求 adapter
  parsers/         # 每个 provider 一个 parser
  types.py         # 统一数据模型
  utils.py         # 归一化工具
scripts/
  search_web.py
  batch_test_search.py
```

## CLI 参数

- `--count`：每个 engine 请求多少条结果；`0` 表示返回完整聚合排序结果。
- `--freshness`：`any`、`day`、`week`、`month`、`year`。
- `--language`：语言提示，例如 `en-US` 或 `zh-CN`。
- `--providers`：指定 provider，例如 `bing,duckduckgo`。
- `--fetch-top`：只抓取第一条搜索结果。
- `--fetch-all`：抓取每一条搜索结果。
- `--fetch-limit`：配合 `--fetch-all` 限制抓取数量；`0` 表示全部。
- `--log-file` / `--clean-log-file`：原始 JSON 日志和可读正文日志。

## 已知限制

- HTML 搜索源可能因为上游页面结构变化而失效。
- 部分 provider 会返回 challenge、`429`、地区限制或空页面。
- HTTP fetch 是 best-effort，不能替代完整浏览器渲染。
- 需要登录或强前端渲染的网站更适合交给 Browser Tool。
- 这个项目优先追求透明、可控和易修改，不追求完美 recall。

## License

如果仓库包含 License 文件，请以该文件为准。
