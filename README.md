# Minimal SearXNG Research Agent

这个项目现在只保留两件事：

1. 一个可被 Agent 通过 LLM `tool_calls` 调用的最小 web search toolset
2. 一个基于该 toolset 的 deep research agent

## Architecture

- `search_web`
  返回 URL、title、snippet、`source_id`
- `read_webpages`
  读取指定 URL，提取正文，返回可用于引用的文档内容
- `search_web_and_read`
  一次调用同时返回检索结果和提取后的正文
- `finish_research`
  供 LLM 在“证据已足够”时显式结束研究阶段

Deep research 流程：

1. planner 先生成 2 到 4 个检索 query
2. researcher 使用标准 OpenAI-compatible `tool_calls` 循环调用工具
3. writer 基于最终证据写出带 `[S1]` 引用的 Markdown

现在 planner 和 researcher 都通过显式 `tools` 参数与 LLM 交互，不再依赖让模型在正文里输出 JSON 再解析。

## Files

```text
app/
  agent.py
  cli.py
  config.py
  llm.py
  main.py
  schemas.py
  tools/
    registry.py
    web.py
```

## Setup

### 1. Configure Docker and SearXNG

```bash
cd /Users/tongbu/Projects/websearch
docker compose up -d searxng
```

常用命令：

```bash
docker compose ps
docker compose logs -f searxng
docker compose stop searxng
docker compose start searxng
docker compose up -d searxng
```

说明：

- `up -d searxng` 用于首次启动，或容器不存在时重新创建。
- `start searxng` 只适用于容器已经创建但当前是 stopped 的情况。
- agent/tool 默认会在搜索前检查 SearXNG；如果没启动，会自动执行 `docker compose up -d searxng`。

### 2. Test SearXNG Directly

健康检查：

```bash
curl -s "http://127.0.0.1:8080/search?q=healthcheck&format=json"
```

简单搜索测试：

```bash
curl -s "http://127.0.0.1:8080/search?q=searxng&format=json"
```

确认容器状态：

```bash
docker compose ps searxng
```

### 3. Configure `.env`

支持两组环境变量名：

```env
SEARXNG_BASE_URL=http://127.0.0.1:8080
SEARXNG_AUTO_START=true
SEARXNG_COMPOSE_DIR=.
SEARXNG_SERVICE_NAME=searxng
SEARXNG_STARTUP_TIMEOUT_SECONDS=30

LLM_PROVIDER=openai_compatible
LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL=...
```

或者：

```env
OPENAI_BASE_URL=...
OPENAI_API_KEY=...
OPENAI_MODEL=...
LLM_PROVIDER=openai_compatible
```

如果没有配置真实模型，默认走 `mock`，方便本地验证流程。

如果 `.env` 中存在 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`，即使没有显式设置 `LLM_PROVIDER`，代码也会自动切到 `openai_compatible`。

自动启动相关配置：

- `SEARXNG_AUTO_START=true`
  搜索前自动检查并尝试拉起 SearXNG
- `SEARXNG_COMPOSE_DIR=.`
  `docker-compose.yml` 所在目录，相对路径基于项目根目录
- `SEARXNG_SERVICE_NAME=searxng`
  compose service 名
- `SEARXNG_STARTUP_TIMEOUT_SECONDS=30`
  自动启动后的等待时间

日志相关配置：

- `LOG_LEVEL=INFO`
  默认打印 planner、tool call、tool result、fallback、最终元数据
- `LOG_PAYLOAD_CHARS=1200`
  单条日志最大 payload 长度
- `LOG_LLM_RAW=false`
  设为 `true` 时额外打印 LLM 原始返回里的 `content` 和 `tool_calls` 摘要
- `LOG_DIR=logs`
  日志目录，默认写到项目根目录下的 `logs/`
- `LOG_FILE_NAME=websearch.log`
  日志文件名
- `LOG_FILE_MAX_BYTES=5000000`
  单个日志文件最大大小，超过后滚动
- `LOG_FILE_BACKUP_COUNT=3`
  保留的历史日志文件数量

### 4. Install

```bash
pip install -r requirements.txt
```

## Run

### CLI

```bash
python3 -m app.cli --show-tools
python3 -m app.cli "How can I build a minimal web research agent?"
```

### HTTP

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

如果要看更详细的真实模型 tool call 日志，可以在 `.env` 中加：

```env
LOG_LEVEL=INFO
LOG_LLM_RAW=true
LOG_PAYLOAD_CHARS=2000
```

默认日志会同时输出到终端和日志文件：

```text
/Users/tongbu/Projects/websearch/logs/websearch.log
```

## Tool Test

查看 tool schema：

```bash
curl -s http://127.0.0.1:8000/tools
```

测试“只返回 URL 列表”的搜索：

```bash
curl -s -X POST "http://127.0.0.1:8000/tool-call" \
  -H "Content-Type: application/json" \
  -d '{"name":"search_web","arguments":{"query":"minimal deep research agent","max_results":5}}'
```

测试“搜索并解析正文”：

```bash
curl -s -X POST "http://127.0.0.1:8000/tool-call" \
  -H "Content-Type: application/json" \
  -d '{"name":"search_web_and_read","arguments":{"query":"minimal deep research agent","max_results":3}}'
```

测试“读取指定页面”：

```bash
curl -s -X POST "http://127.0.0.1:8000/tool-call" \
  -H "Content-Type: application/json" \
  -d '{"name":"read_webpages","arguments":{"pages":[{"source_id":"S1","url":"https://docs.searxng.org/","title":"SearXNG docs"}]}}'
```

## Deep Research Test

### 1. Mock 模式

如果没有真实 LLM，保持默认 `LLM_PROVIDER=mock` 即可。

CLI：

```bash
python3 -m app.cli "How can I build a minimal deep research agent with SearXNG?"
```

HTTP：

```bash
curl -s -X POST "http://127.0.0.1:8000/deep-research" \
  -H "Content-Type: application/json" \
  -d '{"question":"How can I build a minimal deep research agent with SearXNG?","save_markdown":true}'
```

建议检查：

- `plan.search_queries` 是否合理
- `metadata.tool_calls` 是否大于 0
- `metadata.num_search_results` 是否大于 0
- `metadata.num_documents_read` 是否大于 0
- `sources` 是否带有 URL 和 score
- `markdown` 是否包含 `[S1]` 这类引用

### 2. Real LLM 模式

设置：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL=...
```

然后重复上面的 CLI 或 HTTP 测试。此时重点看：

- planner 是否生成 2 到 4 个不同 query
- agent 是否会多轮调用 `search_web`、`read_webpages`、`finish_research`
- 最终答案是否只引用已读取过的 source

## Notes

- 所有 tool 参数都经过 Pydantic 校验，适合做 LLM function calling 的执行层。
- 返回既支持“只看 URL 列表”，也支持“返回解析拼接后的正文内容”。
- 代码去掉了原来分散的 LLM / search / read / rerank 文件，减少重复入口和 fallback 分叉。
- 搜索前默认会自检 SearXNG；如果服务不可达，会尝试用 Docker Compose 自动拉起。
