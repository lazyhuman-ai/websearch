from __future__ import annotations

import ast
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.logging_utils import truncate_for_log
from app.schemas import ChatMessage, ChatResponse, ResearchPlan, ResearchPlanToolArgs, ToolCall, WebDocument

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatResponse:
        raise NotImplementedError


class MockLLMClient(BaseLLMClient):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatResponse:
        if tools:
            tool_names = {item.get("function", {}).get("name") for item in tools}
            if "submit_research_plan" in tool_names:
                return self._planner_tool_response(messages)
            return self._tool_loop_response(messages)

        prompt = messages[-1].content or ""
        if "Write the final answer in Markdown" in prompt:
            return ChatResponse(content=self._mock_markdown(messages))

        return ChatResponse(content="{}")

    def _planner_tool_response(self, messages: list[ChatMessage]) -> ChatResponse:
        query = self._extract_queries_from_prompt(messages[-1].content or "")[0]
        return ChatResponse(
            tool_calls=[
                ToolCall(
                    id="tool_plan_1",
                    name="submit_research_plan",
                    arguments={
                        "rewritten_question": query,
                        "needs_freshness": False,
                        "date_context": None,
                        "search_queries": [query],
                        "notes": ["mock planner"],
                    },
                    raw_arguments=json.dumps(
                        {
                            "rewritten_question": query,
                            "needs_freshness": False,
                            "date_context": None,
                            "search_queries": [query],
                            "notes": ["mock planner"],
                        },
                        ensure_ascii=False,
                    ),
                )
            ]
        )

    def _tool_loop_response(self, messages: list[ChatMessage]) -> ChatResponse:
        tool_payloads = [self._loads(message.content) for message in messages if message.role == "tool" and message.content]
        if not tool_payloads:
            query = self._extract_queries_from_prompt(messages[-1].content or "")[0]
            return ChatResponse(
                tool_calls=[
                    ToolCall(
                        id="tool_search_1",
                        name="search_web",
                        arguments={"query": query, "max_results": 5},
                    )
                ]
            )

        search_payload = next((payload for payload in reversed(tool_payloads) if "results" in payload), None)
        read_payload = next((payload for payload in reversed(tool_payloads) if "documents" in payload), None)

        if search_payload and not read_payload:
            pages = [
                {"source_id": item["source_id"], "url": item["url"], "title": item.get("title", "")}
                for item in search_payload.get("results", [])[:3]
            ]
            return ChatResponse(
                tool_calls=[
                    ToolCall(
                        id="tool_read_1",
                        name="read_webpages",
                        arguments={"pages": pages},
                    )
                ]
            )

        documents = (read_payload or {}).get("documents", [])
        return ChatResponse(
            tool_calls=[
                ToolCall(
                    id="tool_finish_1",
                    name="finish_research",
                    arguments={
                        "summary": "Collected initial evidence and selected top readable sources.",
                        "source_ids": [item["source_id"] for item in documents[:3]],
                    },
                )
            ]
        )

    def _extract_queries_from_prompt(self, prompt: str) -> list[str]:
        question = prompt.split("Question:", 1)[-1].strip().splitlines()[0] if "Question:" in prompt else "web research"
        return [question]

    def _mock_markdown(self, messages: list[ChatMessage]) -> str:
        tool_payloads = [self._loads(message.content) for message in messages if message.role == "tool" and message.content]
        documents: list[dict[str, Any]] = []
        for payload in tool_payloads:
            documents.extend(payload.get("documents", []))

        source_lines = [
            f"- [{item['source_id']}] {item['title']} - {item['url']}"
            for item in documents[:5]
        ]
        citation = f"[{documents[0]['source_id']}]" if documents else "[S1]"
        return (
            "# Research Answer\n\n"
            "## Key Findings\n\n"
            f"- A minimal deep research stack should separate planning, search, reading, and synthesis {citation}.\n\n"
            "## Evidence and Analysis\n\n"
            f"The current implementation exposes agent tools for search and page reading, which is the core pattern used by mainstream tool-using research agents {citation}.\n\n"
            "## Gaps / Uncertainty\n\n"
            "- Mock mode does not validate a real model's retrieval quality.\n\n"
            "## Sources\n\n"
            + ("\n".join(source_lines) if source_lines else "- None")
        )

    @staticmethod
    def _loads(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}


class OpenAICompatibleLLMClient(BaseLLMClient):
    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatResponse:
        settings = get_settings()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.model_dump(exclude_none=True) for message in messages],
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self.base_url}/chat/completions"

        try:
            with httpx.Client(timeout=settings.request_timeout_seconds * 3) as client:
                response = client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("LLM returned invalid JSON") from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("LLM returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""

        tool_calls: list[ToolCall] = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            arguments_text = function.get("arguments") or "{}"
            parsed_arguments, parse_error = _safe_json_loads_with_error(arguments_text)
            tool_calls.append(
                ToolCall(
                    id=str(item.get("id") or function.get("name") or "tool_call"),
                    name=str(function.get("name") or ""),
                    arguments=parsed_arguments,
                    raw_arguments=arguments_text,
                    parse_error=parse_error,
                )
            )
        if settings.log_llm_raw:
            logger.info(
                "llm_response content=%s tool_calls=%s",
                truncate_for_log(content),
                truncate_for_log(tool_calls),
            )

        return ChatResponse(content=content.strip(), tool_calls=tool_calls, raw=data)


def get_llm_client() -> BaseLLMClient:
    settings = get_settings()
    provider = settings.llm_provider.strip().lower()
    if provider == "mock" and settings.llm_api_key and settings.llm_base_url and settings.llm_model:
        provider = "openai_compatible"
    if provider == "mock":
        return MockLLMClient()
    if provider in {"openai", "openai_compatible"}:
        if not settings.llm_api_key or not settings.llm_base_url or not settings.llm_model:
            raise ValueError("LLM API config is incomplete. Set provider, base URL, API key, and model.")
        return OpenAICompatibleLLMClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


def plan_question(question: str, today_text: str) -> ResearchPlan:
    planner_tool = {
        "type": "function",
        "function": {
            "name": "submit_research_plan",
            "description": (
                "Submit the research plan. Use this function exactly once with the rewritten question, "
                "freshness decision, optional date context, 2 to 4 search queries, and short notes."
            ),
            "parameters": ResearchPlanToolArgs.model_json_schema(),
        },
    }
    messages = [
        ChatMessage(
            role="system",
            content=(
                "You are a research planner. "
                "You must respond by calling the provided tool exactly once. "
                "Do not answer in plain text. "
                "Decide whether freshness matters and propose 2 to 4 web search queries."
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"Today's date: {today_text}\n"
                f"Question: {question}\n\n"
                "Call the tool with fields: rewritten_question, needs_freshness, date_context, search_queries, notes.\n"
                "search_queries must contain 2 to 4 strings.\n"
                "notes must contain short strings.\n"
                "date_context must be null or a short date string."
            ),
        ),
    ]
    response = get_llm_client().chat(
        messages,
        tools=[planner_tool],
        tool_choice={"type": "function", "function": {"name": "submit_research_plan"}},
    )
    plan_call = next((call for call in response.tool_calls if call.name == "submit_research_plan"), None)
    if plan_call is None:
        raise ValueError("Planner did not call submit_research_plan")
    if plan_call.parse_error:
        raise ValueError(f"Planner returned invalid tool arguments: {plan_call.parse_error}")
    try:
        payload = ResearchPlanToolArgs.model_validate(plan_call.arguments)
    except ValidationError as exc:
        raise ValueError(f"Planner returned invalid plan schema: {exc}") from exc
    queries = [str(item).strip() for item in payload.search_queries if str(item).strip()]
    if not queries:
        raise ValueError("Planner did not return search queries")
    return ResearchPlan(
        original_question=question,
        rewritten_question=payload.rewritten_question or question,
        needs_freshness=payload.needs_freshness,
        date_context=payload.date_context,
        search_queries=queries,
        notes=[str(item).strip() for item in payload.notes if str(item).strip()],
    )


def synthesize_markdown(question: str, plan: ResearchPlan, documents: list[WebDocument]) -> str:
    allowed_source_ids = [document.source_id for document in documents]
    sources_block = "\n\n".join(
        [
            "\n".join(
                [
                    f"[{document.source_id}] {document.title}",
                    f"URL: {document.url}",
                    "Content:",
                    document.content,
                ]
            )
            for document in documents
        ]
    )
    messages = [
        ChatMessage(
            role="system",
            content=(
                "You are a careful deep research writer. Use only the provided sources. "
                "Write the final answer in Markdown with inline citations like [S1]. "
                "Only cite source IDs that exist in the provided sources."
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"Question: {question}\n"
                f"Rewritten question: {plan.rewritten_question}\n"
                f"Freshness needed: {plan.needs_freshness}\n"
                f"Date context: {plan.date_context or 'none'}\n"
                f"Queries used: {json.dumps(plan.search_queries, ensure_ascii=False)}\n\n"
                f"Sources:\n{sources_block}\n\n"
                f"Allowed citation IDs: {allowed_source_ids}\n\n"
                "Write the final answer in Markdown with these sections only:\n"
                "# Research Answer\n"
                "## Key Findings\n"
                "## Evidence and Analysis\n"
                "## Gaps / Uncertainty\n"
                "Do not write a Sources section. "
                "Every bullet in Key Findings and every paragraph in Evidence and Analysis must include at least one inline citation. "
                "If evidence is uncertain, say so and still cite the closest supporting source."
            ),
        ),
    ]
    client = get_llm_client()
    draft = client.chat(messages).content.strip()
    body = _strip_sources_section(draft)
    valid, issues = _validate_citation_body(body, allowed_source_ids)
    if not valid:
        logger.warning("citation_validation_failed issues=%s", issues)
        repair_messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are repairing citations in a research draft. "
                    "Return only corrected Markdown. "
                    "Do not add a Sources section. "
                    "Only use allowed citation IDs."
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"Allowed citation IDs: {allowed_source_ids}\n"
                    f"Issues to fix: {issues}\n\n"
                    "Correct this Markdown so that every claim uses only allowed citation IDs and the Key Findings / Evidence sections contain inline citations:\n\n"
                    f"{body}"
                ),
            ),
        ]
        body = _strip_sources_section(client.chat(repair_messages).content.strip())
        logger.info("citation_validation_repaired")
    body = _ensure_required_sections(body)
    return body.rstrip() + "\n\n" + _render_sources_section(documents)


def _safe_json_loads(text: str) -> dict[str, Any]:
    parsed, _ = _safe_json_loads_with_error(text)
    return parsed


def _safe_json_loads_with_error(text: str) -> tuple[dict[str, Any], str | None]:
    candidates = _json_candidates(text)
    for candidate in candidates:
        parsed = _try_parse_json_candidate(candidate)
        if isinstance(parsed, dict):
            return parsed, None
    error = f"Invalid JSON object: {truncate_for_log(text)}"
    logger.warning("json_parse_failed payload=%s", truncate_for_log(text))
    return {}, error


def _strip_sources_section(markdown: str) -> str:
    return re.sub(r"\n## Sources\b.*$", "", markdown.strip(), flags=re.S).strip()


def _validate_citation_body(markdown: str, allowed_source_ids: list[str]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    allowed = set(allowed_source_ids)
    citations = re.findall(r"\[([A-Za-z]\d+)\]", markdown)
    if not citations:
        issues.append("No inline citations were found.")
    invalid = sorted({citation for citation in citations if citation not in allowed})
    if invalid:
        issues.append(f"Invalid citation IDs found: {invalid}")

    key_findings = _section_content(markdown, "Key Findings")
    evidence = _section_content(markdown, "Evidence and Analysis")
    if key_findings:
        for line in [line.strip() for line in key_findings.splitlines() if line.strip().startswith("-")]:
            if not re.search(r"\[[A-Za-z]\d+\]", line):
                issues.append(f"Key Findings bullet missing citation: {line}")
    else:
        issues.append("Missing Key Findings section content.")

    if evidence:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", evidence) if part.strip()]
        for paragraph in paragraphs:
            if not re.search(r"\[[A-Za-z]\d+\]", paragraph):
                issues.append(f"Evidence paragraph missing citation: {truncate_for_log(paragraph, 200)}")
    else:
        issues.append("Missing Evidence and Analysis section content.")

    return not issues, issues


def _section_content(markdown: str, heading: str) -> str:
    pattern = rf"## {re.escape(heading)}\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, markdown, re.S)
    return match.group(1).strip() if match else ""


def _ensure_required_sections(markdown: str) -> str:
    text = markdown.strip()
    if not text.startswith("# Research Answer"):
        text = "# Research Answer\n\n" + text
    for heading in ["## Key Findings", "## Evidence and Analysis", "## Gaps / Uncertainty"]:
        if heading not in text:
            text += "\n\n" + heading + "\n\n- Missing section."
    return text


def _render_sources_section(documents: list[WebDocument]) -> str:
    lines = ["## Sources", ""]
    for document in documents:
        lines.append(f"- [{document.source_id}] {document.title} - {document.url}")
    return "\n".join(lines)


def _json_candidates(text: str) -> list[str]:
    normalized = (text or "").strip()
    if not normalized:
        return []

    candidates: list[str] = [normalized]

    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", normalized, flags=re.S)
    if fenced != normalized:
        candidates.append(fenced.strip())

    balanced = _extract_balanced_json_object(normalized)
    if balanced:
        candidates.append(balanced)

    cleaned = _cleanup_json_like_text(normalized)
    if cleaned != normalized:
        candidates.append(cleaned)

    if balanced:
        cleaned_balanced = _cleanup_json_like_text(balanced)
        if cleaned_balanced != balanced:
            candidates.append(cleaned_balanced)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        stripped = candidate.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        deduped.append(stripped)
    return deduped


def _try_parse_json_candidate(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text, strict=False)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    try:
        repaired = re.sub(r",\s*([}\]])", r"\1", text)
        parsed = json.loads(repaired, strict=False)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    python_like = text
    python_like = re.sub(r"\btrue\b", "True", python_like, flags=re.I)
    python_like = re.sub(r"\bfalse\b", "False", python_like, flags=re.I)
    python_like = re.sub(r"\bnull\b", "None", python_like, flags=re.I)
    try:
        parsed = ast.literal_eval(python_like)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, SyntaxError):
        return None


def _cleanup_json_like_text(text: str) -> str:
    cleaned = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", cleaned)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned.strip()


def _extract_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None
