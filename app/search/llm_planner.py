from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.search.types import SearchRequest


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
VALID_CATEGORIES = {"general", "news", "reference", "academic", "code"}


@dataclass(slots=True)
class PlannerDecision:
    engines: list[str]
    normalized_query: str
    category: str
    used_llm: bool = False
    reason: str = ""


class LLMPlanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.last_error: str = ""

    def is_enabled(self) -> bool:
        return bool(
            self.settings.llm_planner_enabled
            and self.settings.llm_api_key
            and self.settings.llm_model
        )

    def plan(
        self,
        request: SearchRequest,
        *,
        available_engines: list[str],
        engine_groups: dict[str, list[str]],
        default_category: str,
    ) -> PlannerDecision | None:
        if not self.is_enabled():
            self.last_error = "planner_disabled_or_missing_credentials"
            return None
        payload = self._call_llm(request, available_engines=available_engines, engine_groups=engine_groups, default_category=default_category)
        if not payload:
            return None
        normalized_query = str(payload.get("normalized_query") or request.query).strip() or request.query
        category = str(payload.get("category") or default_category).strip().lower()
        if category not in VALID_CATEGORIES:
            category = default_category
        requested_engines = payload.get("engines")
        engines = [str(name).strip() for name in requested_engines if str(name).strip() in available_engines] if isinstance(requested_engines, list) else []
        if not engines:
            base_engines = [name for name in engine_groups.get("general", []) if name in available_engines]
            specialized_engines = [name for name in engine_groups.get(category, []) if name in available_engines] if category != "general" else []
            engines = self._merge_engines(base_engines, specialized_engines)
        if not engines:
            return None
        reason = str(payload.get("reason") or "")
        return PlannerDecision(engines=engines, normalized_query=normalized_query, category=category, used_llm=True, reason=reason)

    def _call_llm(
        self,
        request: SearchRequest,
        *,
        available_engines: list[str],
        engine_groups: dict[str, list[str]],
        default_category: str,
    ) -> dict[str, object] | None:
        base_url = self.settings.llm_base_url.rstrip("/")
        endpoint = f"{base_url}/chat/completions"
        responses_endpoint = f"{base_url}/responses"
        system_prompt = (
            "Return strict JSON only. "
            "You plan web search. "
            "Clean the query for search quality. "
            "Use broad web engines as the base for all searches. "
            "Add specialized engines only for academic, code, reference, or news queries. "
            "Do not invent engine names."
        )
        user_prompt = json.dumps(
            {
                "query": request.query,
                "category": request.category,
                "language": request.language,
                "site": request.site,
                "default_category": default_category,
                "available_engines": available_engines,
                "base_engines": engine_groups.get("general", []),
                "specialized_engines": {
                    "news": engine_groups.get("news", []),
                    "reference": engine_groups.get("reference", []),
                    "academic": engine_groups.get("academic", []),
                    "code": engine_groups.get("code", []),
                },
                "response_schema": {
                    "normalized_query": "string",
                    "category": "general|news|reference|academic|code",
                    "engines": ["engine_name"],
                    "reason": "short string",
                },
            },
            ensure_ascii=False,
        )
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        attempts = [
            (
                endpoint,
                {
                    "model": self.settings.llm_model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            ),
            (
                endpoint,
                {
                    "model": self.settings.llm_model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            ),
            (
                responses_endpoint,
                {
                    "model": self.settings.llm_model,
                    "temperature": 0,
                    "input": [
                        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                        {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
                    ],
                },
            ),
        ]
        response: httpx.Response | None = None
        last_exc: Exception | None = None
        with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
            for target, body in attempts:
                try:
                    candidate = client.post(target, headers=headers, json=body)
                    candidate.raise_for_status()
                    response = candidate
                    break
                except httpx.HTTPError as exc:
                    last_exc = exc
                    continue
        if response is None:
            self.last_error = f"http_error: {last_exc}" if last_exc is not None else "http_error: no_response"
            return None
        try:
            payload = response.json()
            content = self._extract_content(payload)
            parsed = self._parse_json(str(content or ""))
            if parsed is None:
                self.last_error = "invalid_llm_json"
            else:
                self.last_error = ""
            return parsed
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            self.last_error = "invalid_llm_payload"
            return None

    def _parse_json(self, content: str) -> dict[str, object] | None:
        content = content.strip()
        if not content:
            return None
        match = JSON_BLOCK_RE.search(content)
        if match:
            content = match.group(1)
        else:
            content = self._extract_json_object(content)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _extract_json_object(self, content: str) -> str:
        start = content.find("{")
        if start < 0:
            return content
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(content)):
            char = content[index]
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
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return content[start : index + 1]
        return content

    def _merge_engines(self, base: list[str], extra: list[str]) -> list[str]:
        merged = list(base)
        for name in extra:
            if name not in merged:
                merged.append(name)
        return merged

    def _extract_content(self, payload: dict[str, object]) -> str:
        if isinstance(payload.get("output_text"), str):
            return str(payload.get("output_text") or "")
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        fragments: list[str] = []
                        for item in content:
                            if isinstance(item, dict):
                                text = item.get("text")
                                if isinstance(text, str):
                                    fragments.append(text)
                        return "".join(fragments)
                text = first.get("text")
                if isinstance(text, str):
                    return text
        output = payload.get("output")
        if isinstance(output, list):
            fragments: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict):
                        text = block.get("text")
                        if isinstance(text, str):
                            fragments.append(text)
            if fragments:
                return "".join(fragments)
        return ""
