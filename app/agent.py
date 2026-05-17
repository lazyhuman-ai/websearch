from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.llm import get_llm_client, plan_question, synthesize_markdown
from app.logging_utils import configure_logging, truncate_for_log
from app.schemas import ChatMessage, DeepResearchMetadata, DeepResearchResponse, ResearchPlan, ResearchSource, WebDocument
from app.tools.registry import InvalidToolArgumentsError, ToolRegistry, UnknownToolError, dump_tool_result

logger = logging.getLogger(__name__)


def _slugify(value: str, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug[:max_length] or "research"


class DeepResearchAgent:
    def __init__(self) -> None:
        configure_logging()
        self.settings = get_settings()
        self.llm = get_llm_client()
        self.tools = ToolRegistry()

    def run(self, question: str, save_markdown: bool = True, output_dir: str = "research_outputs") -> DeepResearchResponse:
        logger.info("deep_research_start question=%s save_markdown=%s output_dir=%s", question, save_markdown, output_dir)
        plan = self._plan(question)
        documents, tool_calls, searched_urls, finished = self._run_research_loop(question, plan)
        final_documents = self._prepare_final_documents(plan.rewritten_question, documents, finished=finished)
        markdown = self._render_markdown(question, plan, final_documents)
        markdown_path = self._save_markdown(markdown, question, output_dir) if save_markdown else None

        sources = [
            ResearchSource(
                source_id=document.source_id,
                title=document.title,
                url=document.url,
                score=document.score,
            )
            for document in final_documents
        ]
        metadata = DeepResearchMetadata(
            num_search_results=len(searched_urls),
            num_documents_read=sum(1 for document in documents if document.success),
            num_sources_used=len(final_documents),
            tool_calls=tool_calls,
            markdown_path=markdown_path,
            plan_queries=plan.search_queries,
            visited_urls=[document.url for document in documents],
        )
        logger.info(
            "deep_research_done searched_urls=%s documents_read=%s sources_used=%s tool_calls=%s markdown_path=%s",
            metadata.num_search_results,
            metadata.num_documents_read,
            metadata.num_sources_used,
            metadata.tool_calls,
            metadata.markdown_path,
        )
        return DeepResearchResponse(
            question=question,
            plan=plan,
            answer=markdown,
            markdown=markdown,
            sources=sources,
            metadata=metadata,
        )

    def _plan(self, question: str) -> ResearchPlan:
        today_text = datetime.now().strftime("%Y-%m-%d")
        try:
            plan = plan_question(question, today_text)
            logger.info("planner_success plan=%s", truncate_for_log(plan.model_dump(mode="json")))
        except Exception:
            plan = self._fallback_plan(question)
            logger.exception("planner_failed_using_fallback question=%s", question)
        plan = self._normalize_plan(question, plan)
        plan.search_queries = self._dedupe_queries(plan.search_queries or self._fallback_plan(question).search_queries)
        logger.info("planner_queries queries=%s", plan.search_queries)
        return plan

    def _run_research_loop(self, question: str, plan: ResearchPlan) -> tuple[list[WebDocument], int, set[str], bool]:
        tool_messages: list[ChatMessage] = []
        documents_by_id: dict[str, WebDocument] = {}
        searched_urls: set[str] = set()
        url_to_source_id: dict[str, str] = {}
        source_id_aliases: dict[str, str] = {}
        tool_calls = 0
        seen_search_queries: set[str] = set()
        consecutive_zero_result_searches = 0

        for step in range(1, self.settings.agent_max_steps + 1):
            logger.info("research_step_start step=%s known_documents=%s searched_urls=%s", step, len(documents_by_id), len(searched_urls))
            messages = self._build_research_messages(question, plan, tool_messages)
            response = self.llm.chat(messages, tools=self.tools.list_openai_schemas(), tool_choice="auto")
            if not response.tool_calls:
                logger.info("research_step_no_tool_calls step=%s content=%s", step, truncate_for_log(response.content))
                break

            tool_messages.append(
                ChatMessage(
                    role="assistant",
                    content=response.content or "",
                    tool_calls=[
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": call.raw_arguments
                                or json.dumps(call.arguments, ensure_ascii=False),
                            },
                        }
                        for call in response.tool_calls
                    ],
                )
            )
            for call in response.tool_calls:
                tool_calls += 1
                if call.parse_error:
                    logger.warning(
                        "tool_call_invalid_json step=%s call_id=%s tool=%s error=%s raw_arguments=%s",
                        step,
                        call.id,
                        call.name,
                        call.parse_error,
                        truncate_for_log(call.raw_arguments or ""),
                    )
                    result = self._build_invalid_tool_call_result(call)
                    tool_messages.append(
                        ChatMessage(
                            role="tool",
                            tool_call_id=call.id,
                            name=call.name,
                            content=dump_tool_result(result),
                        )
                    )
                    continue

                logger.info(
                    "tool_call step=%s call_id=%s tool=%s arguments=%s",
                    step,
                    call.id,
                    call.name,
                    truncate_for_log(json.dumps(call.arguments, ensure_ascii=False)),
                )
                if call.name == "search_web":
                    query = str(call.arguments.get("query") or "").strip().lower()
                    if len(seen_search_queries) >= self.settings.max_queries_per_task:
                        result = {
                            "error": "search_budget_exceeded",
                            "tool_name": call.name,
                            "message": (
                                f"The task has already used {self.settings.max_queries_per_task} search queries. "
                                "Reuse existing results, read pages, or finish the research."
                            ),
                            "arguments": call.arguments,
                        }
                        logger.info(
                            "tool_call_search_budget_exceeded step=%s call_id=%s used_queries=%s",
                            step,
                            call.id,
                            len(seen_search_queries),
                        )
                        tool_messages.append(
                            ChatMessage(
                                role="tool",
                                tool_call_id=call.id,
                                name=call.name,
                                content=dump_tool_result(result),
                            )
                        )
                        continue
                    if query and query in seen_search_queries:
                        result = {
                            "error": "duplicate_search_query",
                            "tool_name": call.name,
                            "message": "This search query was already executed. Reuse prior results or try a meaningfully different query.",
                            "arguments": call.arguments,
                        }
                        logger.info(
                            "tool_call_duplicate_search step=%s call_id=%s tool=%s query=%s",
                            step,
                            call.id,
                            call.name,
                            query,
                        )
                        tool_messages.append(
                            ChatMessage(
                                role="tool",
                                tool_call_id=call.id,
                                name=call.name,
                                content=dump_tool_result(result),
                            )
                        )
                        continue
                try:
                    result = self.tools.execute(call.name, call.arguments)
                except InvalidToolArgumentsError as exc:
                    result = self._build_invalid_tool_schema_result(call, str(exc))
                    logger.warning(
                        "tool_call_invalid_schema step=%s call_id=%s tool=%s error=%s arguments=%s",
                        step,
                        call.id,
                        call.name,
                        str(exc),
                        truncate_for_log(json.dumps(call.arguments, ensure_ascii=False)),
                    )
                except UnknownToolError as exc:
                    result = self._build_unknown_tool_result(call, str(exc))
                    logger.warning(
                        "tool_call_unknown_tool step=%s call_id=%s tool=%s error=%s",
                        step,
                        call.id,
                        call.name,
                        str(exc),
                    )
                except Exception as exc:
                    result = {
                        "error": str(exc),
                        "tool_name": call.name,
                        "arguments": call.arguments,
                    }
                    logger.exception("tool_call_failed step=%s call_id=%s tool=%s", step, call.id, call.name)
                else:
                    result = self._normalize_tool_result(result, url_to_source_id, source_id_aliases)
                    logger.info(
                        "tool_result step=%s call_id=%s tool=%s summary=%s",
                        step,
                        call.id,
                        call.name,
                        truncate_for_log(self._summarize_tool_result(result)),
                    )
                tool_messages.append(
                    ChatMessage(
                        role="tool",
                        tool_call_id=call.id,
                        name=call.name,
                        content=dump_tool_result(result),
                    )
                )
                for raw_result in result.get("results", []):
                    url = raw_result.get("url")
                    if url:
                        searched_urls.add(str(url))
                if call.name == "search_web":
                    query = str(call.arguments.get("query") or "").strip().lower()
                    if query:
                        seen_search_queries.add(query)
                    result_count = len(result.get("results", []))
                    consecutive_zero_result_searches = consecutive_zero_result_searches + 1 if result_count == 0 else 0
                    if not documents_by_id and consecutive_zero_result_searches >= self.settings.max_queries_per_task:
                        logger.info(
                            "research_loop_break_on_repeated_zero_results step=%s consecutive_zero_result_searches=%s",
                            step,
                            consecutive_zero_result_searches,
                        )
                        break
                for raw_document in result.get("documents", []):
                    document = WebDocument.model_validate(raw_document)
                    documents_by_id[document.source_id] = document
                if call.name == "finish_research":
                    selected = [
                        source_id_aliases.get(source_id, source_id)
                        for source_id in (result.get("source_ids") or list(documents_by_id))
                    ]
                    documents = [documents_by_id[source_id] for source_id in selected if source_id in documents_by_id]
                    logger.info(
                        "finish_research step=%s selected_source_ids=%s selected_documents=%s",
                        step,
                        selected,
                        len(documents),
                    )
                    return documents or list(documents_by_id.values()), tool_calls, searched_urls, True

        if documents_by_id:
            logger.info("research_loop_return_existing_documents count=%s", len(documents_by_id))
            return list(documents_by_id.values()), tool_calls, searched_urls, False

        fallback_documents = self._run_local_fallback_searches(
            question=question,
            plan=plan,
            searched_urls=searched_urls,
            url_to_source_id=url_to_source_id,
            source_id_aliases=source_id_aliases,
        )
        return fallback_documents, tool_calls, searched_urls, False

    def _build_research_messages(
        self,
        question: str,
        plan: ResearchPlan,
        tool_messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        prompt = (
            "You are a deep research agent. "
            "Use only the provided tools to gather evidence before writing. "
            "Prefer recent, primary, and readable sources when the query asks for latest news or current events. "
            "When reading pages, every page object must contain a valid `url` field. "
            "Tool arguments must be strict JSON with double quotes. "
            "Do not invent tool names. "
            "Call finish_research when you have enough evidence.\n\n"
            f"Question: {question}\n"
            f"Rewritten question: {plan.rewritten_question}\n"
            f"Freshness needed: {plan.needs_freshness}\n"
            f"Date context: {plan.date_context or 'none'}\n"
            f"Initial search queries: {plan.search_queries}\n"
            "\n"
            "Tool usage rules:\n"
            "1. Use `search_web` to explore multiple candidate sources.\n"
            "2. Use `read_webpages` only with objects shaped like {\"source_id\":\"S1\",\"url\":\"https://...\",\"title\":\"...\"}.\n"
            "3. For latest-news questions, search with explicit date terms like 2026 or 'today'.\n"
            "4. After reading enough sources, call `finish_research` with a short summary and selected source_ids.\n"
        )
        return [
            ChatMessage(
                role="system",
                content=(
                    "You are a disciplined research agent that must use tools carefully. "
                    "All tool arguments must be valid JSON objects. "
                    "If you call `read_webpages`, every page entry must include `url`."
                ),
            ),
            ChatMessage(role="user", content=prompt),
            *tool_messages,
        ]

    def _render_markdown(self, question: str, plan: ResearchPlan, documents: list[WebDocument]) -> str:
        if not documents:
            logger.warning("render_markdown_no_documents question=%s", question)
            return (
                "# Research Answer\n\n"
                "## Key Findings\n\n"
                "- No readable sources were gathered.\n\n"
                "## Evidence and Analysis\n\n"
                "- The agent was unable to collect enough source content.\n\n"
                "## Gaps / Uncertainty\n\n"
                "- Search, extraction, or tool usage failed.\n\n"
                "## Sources\n\n"
                "- None"
            )
        try:
            markdown = synthesize_markdown(question, plan, documents)
            logger.info("render_markdown_success documents=%s", len(documents))
            return markdown
        except Exception:
            logger.exception("render_markdown_failed_using_fallback documents=%s", len(documents))
            return self._fallback_markdown(question, documents)

    def _fallback_plan(self, question: str) -> ResearchPlan:
        now = datetime.now()
        needs_freshness = bool(
            re.search(r"\b(latest|lastest|recent|today|current|newest|2024|2025|2026)\b", question, re.I)
        )
        queries = [question.strip(), f"{question.strip()} open source", f"{question.strip()} architecture"]
        if needs_freshness:
            queries.append(f"{question.strip()} {now.year}")
        return ResearchPlan(
            original_question=question,
            rewritten_question=question.strip(),
            needs_freshness=needs_freshness,
            date_context=now.strftime("%Y-%m-%d") if needs_freshness else None,
            search_queries=self._dedupe_queries(queries),
            notes=["heuristic planner"],
        )

    def _fallback_markdown(self, question: str, documents: list[WebDocument]) -> str:
        source_lines = [f"- [{item.source_id}] {item.title} - {item.url}" for item in documents[:5]]
        citation = f"[{documents[0].source_id}]" if documents else "[S1]"
        return (
            "# Research Answer\n\n"
            "## Key Findings\n\n"
            f"- The agent collected evidence relevant to the question {citation}.\n\n"
            "## Evidence and Analysis\n\n"
            f"- The retrieved documents cover the question: {question} {citation}.\n\n"
            "## Gaps / Uncertainty\n\n"
            "- This fallback summary is heuristic and less reliable than LLM synthesis.\n\n"
            "## Sources\n\n"
            + "\n".join(source_lines)
        )

    def _dedupe_queries(self, queries: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for query in queries:
            normalized = query.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped[: max(1, self.settings.max_queries_per_task)]

    def _save_markdown(self, markdown: str, question: str, output_dir: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        directory = Path(output_dir)
        if not directory.is_absolute():
            directory = Path.cwd() / directory
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{timestamp}_{_slugify(question)}.md"
        path.write_text(markdown, encoding="utf-8")
        logger.info("markdown_saved path=%s", path)
        return str(path)

    def _prepare_final_documents(self, query: str, documents: list[WebDocument], *, finished: bool) -> list[WebDocument]:
        readable_documents = [document for document in documents if document.success and document.content.strip()]
        if finished:
            for document in readable_documents:
                document.score = self.tools.web._score_document(query, document)
            return readable_documents
        return self.tools.web.rank_all(query, readable_documents)

    def _normalize_plan(self, question: str, plan: ResearchPlan) -> ResearchPlan:
        needs_freshness = plan.needs_freshness or bool(
            re.search(r"\b(latest|lastest|recent|today|current|newest)\b", question, re.I)
        )
        date_context = plan.date_context
        if needs_freshness and not date_context:
            date_context = datetime.now().strftime("%Y-%m-%d")
        plan.needs_freshness = needs_freshness
        plan.date_context = date_context
        if not plan.search_queries:
            return plan
        if needs_freshness and not any(re.search(r"\b(20\d{2}|today|latest|recent)\b", query, re.I) for query in plan.search_queries):
            plan.search_queries.append(f"{plan.rewritten_question} {datetime.now().year}")
        plan.search_queries = self._dedupe_queries(plan.search_queries)
        return plan

    def _run_local_fallback_searches(
        self,
        *,
        question: str,
        plan: ResearchPlan,
        searched_urls: set[str],
        url_to_source_id: dict[str, str],
        source_id_aliases: dict[str, str],
    ) -> list[WebDocument]:
        fallback_queries = self._build_fallback_search_queries(question, plan)
        logger.info("research_loop_fallback_queries queries=%s", fallback_queries)

        documents: list[WebDocument] = []
        for query in fallback_queries:
            logger.info("research_loop_fallback_search query=%s", query)
            results, read_documents = self.tools.web.search_and_read(
                query,
                max_results=self.settings.search_read_results,
            )
            payload = self._normalize_tool_result(
                {
                    "results": [item.model_dump(mode="json") for item in results],
                    "documents": [item.model_dump(mode="json") for item in read_documents],
                },
                url_to_source_id,
                source_id_aliases,
            )
            searched_urls.update(str(item.url) for item in results)
            normalized_documents = [WebDocument.model_validate(item) for item in payload.get("documents", [])]
            successful_documents = [document for document in normalized_documents if document.success and document.content.strip()]
            logger.info(
                "research_loop_fallback_done query=%s results=%s documents=%s successful_documents=%s",
                query,
                len(results),
                len(normalized_documents),
                len(successful_documents),
            )
            documents.extend(successful_documents)
            if successful_documents:
                break
        return documents

    def _build_fallback_search_queries(self, question: str, plan: ResearchPlan) -> list[str]:
        queries: list[str] = []
        year = str(datetime.now().year)

        def add(query: str) -> None:
            normalized = query.strip()
            if normalized:
                queries.append(normalized)

        for query in plan.search_queries[:4]:
            add(query)
            add(re.sub(r"\b20\d{2}\b", "", query).replace("  ", " ").strip())

        rewritten = plan.rewritten_question or question
        add(rewritten)
        add(re.sub(r"\bin china\b", "China", rewritten, flags=re.I))
        add(re.sub(r"\bchina\b", "", rewritten, flags=re.I).replace("  ", " ").strip())

        if plan.needs_freshness:
            add(f"{rewritten} latest news")
            add(f"{rewritten} {year}")

        lowered = question.lower()
        if "jensen huang" in lowered or "nvidia" in lowered:
            add(f"Jensen Huang Nvidia China {year}")
            add("Jensen Huang Nvidia latest news")
            add("Nvidia China latest news")
            add("Jensen Huang China visit")

        return self._dedupe_queries(queries)

    def _summarize_tool_result(self, result: dict) -> dict:
        summary: dict[str, object] = {}
        if "results" in result:
            results = result.get("results") or []
            summary["results_count"] = len(results)
            summary["result_urls"] = [item.get("url") for item in results[:3] if isinstance(item, dict)]
        if "documents" in result:
            documents = result.get("documents") or []
            summary["documents_count"] = len(documents)
            summary["document_status"] = [
                {
                    "source_id": item.get("source_id"),
                    "success": item.get("success"),
                    "url": item.get("url"),
                }
                for item in documents[:3]
                if isinstance(item, dict)
            ]
        if "summary" in result:
            summary["summary"] = result.get("summary")
        if "source_ids" in result:
            summary["source_ids"] = result.get("source_ids")
        if "error" in result:
            summary["error"] = result.get("error")
        return summary or result

    def _build_invalid_tool_call_result(self, call) -> dict:
        return {
            "error": "invalid_tool_call_json",
            "tool_name": call.name,
            "message": (
                "Your previous tool call arguments were not valid JSON. "
                "Retry the same tool with a strict JSON object that matches the tool schema."
            ),
            "details": call.parse_error,
            "raw_arguments": call.raw_arguments,
            "expected_fix": (
                "Return the tool call again using valid JSON with double-quoted keys and values. "
                "For read_webpages, each page entry must include `url`."
            ),
        }

    def _build_invalid_tool_schema_result(self, call, error_message: str) -> dict:
        return {
            "error": "invalid_tool_call_schema",
            "tool_name": call.name,
            "message": (
                "Your previous tool call arguments were valid JSON, but they did not match the tool schema. "
                "Retry the same tool with all required fields."
            ),
            "details": error_message,
            "arguments": call.arguments,
            "raw_arguments": call.raw_arguments,
            "expected_fix": (
                "Read the tool schema carefully and resend the same tool call with the required fields. "
                "For search_web, include `query`. For read_webpages, each page must include `url`."
            ),
        }

    def _build_unknown_tool_result(self, call, error_message: str) -> dict:
        return {
            "error": "unknown_tool",
            "tool_name": call.name,
            "message": "You called a tool name that does not exist. Retry with one of the provided tools only.",
            "details": error_message,
            "arguments": call.arguments,
            "raw_arguments": call.raw_arguments,
        }

    def _normalize_tool_result(
        self,
        result: dict,
        url_to_source_id: dict[str, str],
        source_id_aliases: dict[str, str],
    ) -> dict:
        normalized = dict(result)

        raw_results = result.get("results") or []
        normalized_results: list[dict] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            url = str(candidate.get("url") or "").strip()
            original_source_id = str(candidate.get("source_id") or "").strip()
            if not url:
                normalized_results.append(candidate)
                continue
            source_id = url_to_source_id.setdefault(url, f"S{len(url_to_source_id) + 1}")
            candidate["source_id"] = source_id
            if original_source_id and original_source_id != source_id:
                source_id_aliases[original_source_id] = source_id
            normalized_results.append(candidate)
        if raw_results:
            normalized["results"] = normalized_results

        raw_documents = result.get("documents") or []
        normalized_documents: list[dict] = []
        for item in raw_documents:
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            url = str(candidate.get("url") or "").strip()
            original_source_id = str(candidate.get("source_id") or "").strip()
            if url:
                source_id = url_to_source_id.setdefault(url, f"S{len(url_to_source_id) + 1}")
                candidate["source_id"] = source_id
                if original_source_id and original_source_id != source_id:
                    source_id_aliases[original_source_id] = source_id
            elif not candidate.get("source_id"):
                candidate["source_id"] = f"S{len(url_to_source_id) + len(normalized_documents) + 1}"
            normalized_documents.append(candidate)
        if raw_documents:
            normalized["documents"] = normalized_documents

        if result.get("source_ids"):
            normalized["source_ids"] = [
                source_id_aliases.get(source_id, source_id)
                for source_id in result.get("source_ids", [])
            ]

        return normalized
