# Python Native Multi-Engine Web Search

一个最小但可扩展的 SearXNG 风格搜索内核。

仓库现在只保留两部分：

- 核心搜索库：`app/search/`
- 手动测试脚本：`scripts/search_web.py`

不包含 agent、前端、HTTP API、session、dataset 或评测框架。

## 目标

这个项目解决的问题不是“调用某一个搜索引擎”，而是：

- 接收一个 query 和少量搜索参数
- 同时请求多个搜索源
- 统一解析不同来源的结果
- 去重、合并、排序
- 返回一个尽可能稳定、可解释的聚合结果

它的设计思路接近 SearXNG，但实现保持最小化，重点放在：

- 多 engine 并发
- 统一结果类型
- 结果清洗与聚合
- 类别感知的 engine 规划

## 实现思路

整体实现分成 4 层：

1. `SearchRequest`
   统一描述一次搜索请求，包括 `query`、`category`、`language`、`page`、`time_range`、`max_results`、`enabled_engines`、`site`。

2. planner
   根据请求内容决定本次应该跑哪些 engine。
   例如：
   - `general` 走通用 web engine
   - `news` 加新闻源
   - `academic` 加 `arxiv`
   - `code` 加 `stackoverflow`、`github`
   - 如果结果太弱，会触发第二轮 fallback engine

3. adapter
   每个搜索源都被包装成统一接口：
   - `fetch`
   - `parse`
   - `normalize`

   当前支持：
   - `google_web`
   - `bing_web`
   - `brave_web`
   - `duckduckgo_lite`
   - `wikipedia`
   - `arxiv`
   - `stackoverflow`
   - `github`
   - `google_news_rss`

4. aggregator
   把多个 engine 的结果统一成内部 `RawSearchHit`，然后：
   - URL normalize
   - tracker removal
   - redirect unwrap
   - canonical URL 去重
   - host + title signature 合并
   - 结合 query overlap、freshness、source prior、多源共识做排序

## 从 Query 到输出结果的完整过程

执行链路如下：

`query -> SearchRequest -> request normalize -> category / intent 识别 -> engine plan -> concurrent fetch -> adapter parse -> RawSearchHit -> normalize -> dedupe / merge / rank -> SearchResponse`

更具体一点：

1. 用户通过 `scripts/search_web.py` 传入 query 和参数。
2. 脚本构造 `SearchRequest`。
3. `SearchClient` 先规范化请求：
   - 修正 `page`
   - 限制 `max_results`
   - 在 `category=auto` 时根据 query 推断类别
   - 如果给了 `site`，把 `site:domain` 注入查询
4. planner 选择一组 engine。
5. 搜索核心并发请求这些 engine。
6. 每个 adapter 解析自己的 HTML / JSON / RSS / API 返回。
7. 所有结果统一转成 `RawSearchHit`。
8. 聚合器清洗 URL，并对重复结果做合并。
9. 排序器按相关性、时效性和来源质量重排。
10. 输出 `SearchResponse`：
   - `query`
   - `request`
   - `used_engines`
   - `results`
   - `engine_failures`
11. 如果加了 `--read`，再对前几个结果抓取正文，附加 `documents`。

## 默认 engine 规划

- `general`
  - `google_web + bing_web + brave_web + duckduckgo_lite`
- `news`
  - `google_web + bing_web + google_news_rss + duckduckgo_lite`
- `reference`
  - `google_web + bing_web + duckduckgo_lite + wikipedia`
- `academic`
  - `google_web + bing_web + arxiv`
- `code`
  - `google_web + bing_web + duckduckgo_lite + stackoverflow + github`

如果显式传 `--engines`，则优先使用指定列表。

## 安装

```bash
pip install -r requirements.txt
```

## 使用方法

最简单的调用：

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
  - 抓取前几个结果正文
- `--pretty`

示例：

```bash
python scripts/search_web.py "latest python news" --category news --max-results 5 --pretty
python scripts/search_web.py "retrieval augmented generation survey" --category academic --time-range year --pretty
python scripts/search_web.py "GitHub Actions permission denied shell script" --category code --pretty
python scripts/search_web.py "asyncio taskgroup" --site docs.python.org --pretty
python scripts/search_web.py "OpenAI API responses" --read --pretty
```

## 输出格式

脚本输出 JSON，核心字段包括：

- `query`
- `request`
- `used_engines`
- `results`
- `engine_failures`
- `documents`
  - 仅在 `--read` 时出现

`results` 中每条结果至少包含：

- `title`
- `url`
- `snippet`
- `engine`
- `engines`
- `published_at`
- `score`

## 测试方法

推荐做 3 层测试。

### 1. 编译检查

确认当前代码没有语法问题：

```bash
PYTHONPYCACHEPREFIX=.pycache python -m py_compile $(find app scripts -name '*.py')
```

如果你使用 `conda`：

```bash
PYTHONPYCACHEPREFIX=.pycache conda run -n demo python -m py_compile $(find app scripts -name '*.py')
```

### 2. 手动 smoke test

至少跑下面 5 类：

```bash
python scripts/search_web.py "what is MVCC" --category general --pretty
python scripts/search_web.py "latest semiconductor news" --category news --pretty
python scripts/search_web.py "BEIR benchmark paper" --category academic --pretty
python scripts/search_web.py "GitHub Actions permission denied shell script" --category code --pretty
python scripts/search_web.py "asyncio taskgroup" --site docs.python.org --pretty
```

测试时重点看：

- `used_engines` 是否符合 planner 预期
- `results` 是否非空
- `engine_failures` 是否只影响单个源，而不是整次失败
- `site` 限定时是否只返回目标域
- `code` / `academic` 类是否命中专用源

### 3. 带正文抓取的测试

```bash
python scripts/search_web.py "OpenAI API responses" --read --pretty
python scripts/search_web.py "latest semiconductor news" --category news --read --pretty
```

重点看：

- `documents[*].success`
- `documents[*].content`
- 新闻聚合链接是否能成功还原正文

## 已知限制

- `google_web`、`brave_web`、`github` 这类 HTML 搜索源会受页面结构变化和反爬影响
- `brave_web` 在某些环境下可能返回 `429`
- `arxiv` 在部分网络环境里可能超时或失败
- `google_news_rss` 常返回聚合包装链接，`--read` 时不一定能抓到正文
- `site` 限定是强过滤；如果上游引擎没给目标域结果，最终会返回空数组
- 这套实现强调“多源聚合结构正确”，不保证每个 query 在所有地区和网络环境下都得到高质量结果
