# Websearch

[English](./README.md) | [简体中文](./README_zh.md)

[项目初衷](#项目初衷) | [当前状态](#当前状态) | [核心架构](#核心架构) | [Roadmap](#roadmap) | [快速开始](#快速开始) | [配置方式](#配置方式) | [已知限制](#已知限制)

一个面向 Agent 的轻量级多引擎 Web Search 基础设施。

这个项目为了给在搭建 Agent Framework、Tool Runtime、Orchestrator 或 Research Stack 时，提供一个轻量级，免部署，可修改的 `websearch tool backend`。

它只包含必要功能：

- 接收一次搜索请求
- 同时调用多个上游搜索引擎
- 把不同格式的结果统一成同一种结构
- 做去重、排序和清洗
- 按 Agent 更容易理解的方式返回结果
- 在需要时再附加 URL 解析和正文提取

## 项目初衷

这个项目是从一个很实际的问题里长出来的：

很多 Agent 系统都需要一个 Web Search Tool，但常见方案都有明显取舍：

- 使用提供商 API 直接 Web Search 很方便，但常常是黑盒，且需求时间金钱成本
- Browser Automation 功能最强，但实现复杂，速度慢
- 单一搜索引擎接入简单，但容易脆弱和受限

于是就有了这个项目：

做一个开放、可改、可解释的 Web Search Backend，作为 Agent 的备选工具层存在。

它适合：

- 作为 Agent Framework 里的 (自定义) websearch tool
- 作为你自己封装工具 API 的底层搜索后端
- 作为避免强绑定某个商业搜索接口的免部署的轻量级替代方案

## 当前状态

这个项目目前仍然是一个比较粗糙、早期阶段的工作。它现在已经可以作为实验性 backend 使用，也适合作为你自定义 Agent Tool 的起点，但它还远远不能被描述成一个“已经完成的、足够鲁棒的 Web Search 系统”。

目前还存在不少明显的粗糙之处：

- 上游搜索引擎页面结构变化会直接影响解析
- 某些结果提取链路仍然比较脆弱
- 排序质量目前只是一个 baseline
- planner 规则不够稳健
- LLM planner 对不同 provider 的兼容性不足
- 自定义配置的支持不足


## 设计目标

- Agent First
  输出结构优先为 LLM 和 Tool 调用服务，而不是为人工阅读优化。
- Multi-Engine by Default
  不把系统设计绑定在单一搜索提供方上。
- Transparent
  planner、used_engines、engine_failures、ranking 逻辑都能被检查。
- Lightweight
  用简单 Python 实现，方便改、方便 fork、方便嵌入。
- Replaceable
  planner、engine adapter、content extraction 可以分开替换。

## 它能做什么

- 多搜索引擎并发搜索
- 按类别路由 query，例如 `general`、`news`、`reference`、`academic`、`code`
- 用 YAML 配置 engine group 和顺序
- 为每个搜索引擎配置多组请求头
- 把不同来源结果统一成一套 schema
- 用 URL 和 title signature 去重
- 一个聊胜于无的排序
- 在需要时解析 URL 并提取可读正文
- 输出结构化日志，方便调试和离线评估

当前内置的上游搜索引擎包括：

- `google_web`
- `bing_web`
- `brave_web`
- `duckduckgo_lite`
- `wikipedia`
- `arxiv`
- `stackoverflow`
- `github`
- `google_news_rss`

## 核心架构

主流程可以概括成：

`SearchRequest -> planner -> engine fanout -> parse -> normalize -> dedupe -> rank -> SearchResponse`

主要组件如下：

- `SearchRequest`
  统一描述一次搜索请求，包括 query、category、language、site、time_range 和 engine request limit。
- `RulePlanner` / `LLMPlanner`
  根据 query 内容决定本次应该使用哪些引擎，并在需要时改写 query。
- `SearchEngine`
  每个上游搜索源一个独立 adapter。
- `SearchClient`
  负责 fanout、聚合、fallback、排序、URL 解析和输出格式。
- `url_tools`
  负责 URL 解析和正文抽取。

## Roadmap

这个项目未来会持续把它打磨成一个更适合 Agent 使用的 Websearch Backend。

### 更多搜索后端

- 增加更多上游搜索后端和 provider adapter
- 把 backend abstraction 做得更清晰，降低切换成本
- 在 HTML 搜索源之外，支持更多 hosted/provider-native backend
- 针对 news、docs、code、academic 等不同类型内容做更细分的源支持

### 更鲁棒的 Web Search

- 提高 HTML 解析对页面结构变动的鲁棒性
- 改进 redirect unwrap 和 wrapper link 恢复能力
- 更好地处理 throttle、challenge page、soft ban 和区域性 interstitial
- 针对不同 backend 设计更清晰的 retry 和 degrade 策略
- 在正文抓取失败时，提供更合理的 fallback 路径

### 排序与结果质量

- 持续增强结果排序，不停留在当前的 heuristic baseline
- 按 category 增加更合理的 source prior
- 引入 domain-level trust 和质量信号
- 改进 news 类 query 的 freshness 排序
- 增强多引擎重叠结果的聚合和共识能力
- 压低视频噪声、包装页、近重复结果等低质量输出

### Planner

- 增加更多 rule-based planner 规则，覆盖更常见的 agent 搜索模式
- 改进对歧义 query、事实查询、时间敏感 query、site-specific query 的改写
- 提升 LLM planner 对不同 provider 和返回格式的兼容性
- 在 LLM 不可用时，提供更稳定的 fallback planner 行为
- 让 planner 的每次决策更容易检查、记录和离线评估

### Agent 集成

- 提供更清晰的 `web_search` / `web_extract` 工具接口
- 增加与常见 agent runtime 的集成示例
- 更清楚地区分 search、fetch、browser escalation 三条路径
- 提供更完善的结构化 telemetry 和调试信息

### 评测与回归

- 增加可重复的搜索质量回归测试
- 建立按 category 组织的 benchmark query 集
- 增加结果质量检查和失败分类工具
- 持续跟踪 planner、engine health 和 extraction quality 的变化

## 项目结构

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

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

最简单的调用：

```bash
python3 scripts/search_web.py "what is CRDT" --pretty
```

新闻搜索：

```bash
python3 scripts/search_web.py "today's news" --category news --pretty
```

代码问题搜索：

```bash
python3 scripts/search_web.py "GitHub Actions permission denied shell script" --category code --pretty
```

站点限定搜索：

```bash
python3 scripts/search_web.py "asyncio taskgroup" --site docs.python.org --pretty
```

附带正文抓取：

```bash
python3 scripts/search_web.py "OpenAI API responses" --read --pretty
```

批量 smoke test：

```bash
python3 scripts/batch_test_search.py --pretty
```
## 配置方式

默认配置文件在 [app/search/search_engines.yaml](./app/search/search_engines.yaml)。

它主要控制三类内容：

- engine group
- disabled engines
- 每个 engine 的 header profiles

示例：

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

常用参数包括：

- `--category`
- `--language`
- `--site`
- `--time-range`
- `--max-results`
  表示每个上游搜索请求希望拿到多少条结果，不是最终返回上限。
- `--max-engine-requests`
  表示每个 engine 最多发多少次分页请求。
- `--engine-config`
- `--resolve-urls` / `--no-resolve-urls`
- `--include-url-content` / `--no-include-url-content`
- `--read`

## 输出格式

CLI 返回 JSON，核心字段包括：

- `query`
- `request`
- `used_engines`
- `results`
- `planner`
- `engine_health`
- `engine_failures`

启用 `--read` 后，还会附带：

- `documents`

## 日志

脚本会输出两类日志：

- 原始 JSON 日志
- clean log
  只保留 URL 和提取后的可读内容，如果正文为空则回退到 `title + snippet`

默认路径：

- `logs/search_web.log`
- `logs/search_web.clean.log`
- `logs/batch_test_search.log`
- `logs/batch_test_search.clean.log`

## 已知限制

- HTML 搜索源容易受页面结构变化影响
- 某些搜索源会触发 challenge、429、地区限制或异常跳转
- Google News 经常返回包装链接而不是源站直链
- 正文提取是 best-effort，不等价于浏览器真实渲染
- 某些页面天然更适合 Browser Tool，而不是 HTTP fetch + extraction
- 这个项目更重视可控性和可解释性，不追求对所有 query 的完美 recall

## 什么时候适合用这个项目

适合：

- 你在做自己的 Agent Framework
- 你想要一个可替换、可自托管的 websearch backend
- 你需要调试为什么某个结果被返回
- 你想研究 query routing、engine selection、ranking

不适合：

- 你只需要浏览器级网页交互
- 你只需要最省事的 vendor-native search
- 你要处理大量需要登录和前端渲染的网站

## License

如果仓库已经有 License，请以仓库内文件为准；如果你准备正式开源，建议补充明确的许可证文件。

## English README

英文版请见 [README.md](/Users/tongbu/lazyhuman-ai/websearch/README.md)。
