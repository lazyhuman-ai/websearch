# Python Native Multi-Engine Web Search

这个仓库只保留核心 web search 能力：

- 一个 SearXNG 风格的多搜索引擎聚合内核
- 一个手动测试脚本 `scripts/search_web.py`

没有 agent、前端、HTTP API、session、dataset、评测脚本。

## Architecture

搜索执行链：

`SearchRequest -> request normalize -> engine planning -> concurrent fetch -> adapter parse -> RawSearchHit -> dedupe/merge/rank -> SearchResponse`

当前支持的 engine：

- `google_web`
- `bing_web`
- `brave_web`
- `duckduckgo_lite`
- `wikipedia`
- `arxiv`
- `github`
- `google_news_rss`

默认 planner 规则：

- `general`
  - `google_web + bing_web + brave_web + duckduckgo_lite`
- `news`
  - `google_web + bing_web + google_news_rss + duckduckgo_lite`
- `reference`
  - `google_web + bing_web + duckduckgo_lite + wikipedia`
- `academic`
  - `google_web + bing_web + arxiv`
- `code`
  - `google_web + bing_web + github`

## Install

```bash
pip install -r requirements.txt
```

## CLI Usage

最简单用法：

```bash
python scripts/search_web.py "what is CRDT" --pretty
```

常用参数：

- `--category`
  - `auto`, `general`, `news`, `reference`, `academic`, `code`
- `--language`
  - 例如 `en-US`, `zh-CN`
- `--page`
- `--time-range`
  - `any`, `day`, `week`, `month`, `year`
- `--max-results`
- `--engines`
  - 逗号分隔，覆盖默认 planner
- `--site`
  - 限定站点，例如 `docs.python.org`
- `--read`
  - 读取并提取前几个结果正文
- `--pretty`

示例：

```bash
python scripts/search_web.py "latest python news" --category news --max-results 5 --pretty
python scripts/search_web.py "retrieval augmented generation survey" --category academic --time-range year --pretty
python scripts/search_web.py "FastAPI 422 Unprocessable Entity" --category code --pretty
python scripts/search_web.py "asyncio taskgroup" --site docs.python.org --pretty
python scripts/search_web.py "OpenAI API responses" --read --pretty
```

## Output

脚本输出 JSON，字段包括：

- `query`
- `request`
- `used_engines`
- `results`
- `engine_failures`
- `documents`
  - 仅在 `--read` 时出现

## Known Limits

- 搜索源中部分 HTML 页面结构会变化，adapter 可能需要跟着调整
- `google_news_rss` 返回的新闻聚合链接并不总能成功还原成可抓取正文
- `brave_web`、`google_web`、`github` 这类 HTML 搜索在不同地区或频率下可能偶发失败
- 单个 engine 失败不会中断整次搜索，失败信息会出现在 `engine_failures`

## Smoke Tests

建议至少手动试这几类：

```bash
python scripts/search_web.py "what is MVCC" --category general --pretty
python scripts/search_web.py "latest semiconductor news" --category news --pretty
python scripts/search_web.py "BEIR benchmark paper" --category academic --pretty
python scripts/search_web.py "GitHub Actions permission denied shell script" --category code --pretty
python scripts/search_web.py "asyncio taskgroup" --site docs.python.org --pretty
```
