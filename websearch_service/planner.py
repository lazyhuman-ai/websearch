from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from websearch_service.config import Settings
from websearch_service.types import SearchRequest


NEWS_HINT_RE = re.compile(r"\b(latest|recent|today|news|headline|breaking)\b", re.I)
ACADEMIC_HINT_RE = re.compile(r"\b(paper|survey|benchmark|arxiv|research)\b", re.I)
CODE_HINT_RE = re.compile(r"\b(github|repo|repository|issue|sdk|library|debug|bug|error|exception)\b", re.I)
REFERENCE_HINT_RE = re.compile(r"\b(who is|what is|history|biography|definition|wiki)\b", re.I)
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
VALID_CATEGORIES = {"general", "news", "reference", "academic", "code"}

ENGINE_GROUPS = {
    "general": ["bing_web", "duckduckgo_lite", "google_web", "brave_web"],
    "news": ["google_news_rss"],
    "reference": ["wikipedia"],
    "academic": ["arxiv"],
    "code": ["stackoverflow", "github"],
    "site": ["google_web", "bing_web", "duckduckgo_lite"],
}
ROUTE_SPECIALIZED_GROUPS = {
    "general": [],
    "news": ["news"],
    "reference": ["reference"],
    "academic": ["academic"],
    "code": ["code"],
}


@dataclass(slots=True)
class PlannerDecision:
    engines: list[str]
    normalized_query: str
    category: str
    used_llm: bool = False
    reason: str = ""


class RulePlanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm_planner = LLMPlanner(settings)

    def infer_category(self, query: str) -> str:
        lowered = query.lower()
        if NEWS_HINT_RE.search(lowered):
            return "news"
        if ACADEMIC_HINT_RE.search(lowered):
            return "academic"
        if CODE_HINT_RE.search(lowered):
            return "code"
        if REFERENCE_HINT_RE.search(lowered):
            return "reference"
        return self.settings.default_category

    def plan_decision(self, request: SearchRequest, available_engines: set[str]) -> PlannerDecision:
        default_category = request.category if request.category != "auto" else self.infer_category(request.query)
        if not request.enabled_engines:
            llm_decision = self.llm_planner.plan(
                request,
                available_engines=sorted(available_engines),
                engine_groups=ENGINE_GROUPS,
                default_category=default_category,
            )
            if llm_decision is not None:
                return PlannerDecision(
                    engines=self._build_route_engines(llm_decision.category, available_engines, request),
                    normalized_query=llm_decision.normalized_query,
                    category=llm_decision.category,
                    used_llm=True,
                    reason=llm_decision.reason or "llm_route_planner",
                )
        return PlannerDecision(
            engines=self.plan(request, available_engines),
            normalized_query=request.query.strip(),
            category=default_category,
            used_llm=False,
            reason=f"rule_planner ({self.llm_planner.last_error})" if self.llm_planner.last_error else "rule_planner",
        )

    def plan(self, request: SearchRequest, available_engines: set[str]) -> list[str]:
        if request.enabled_engines:
            return [name for name in request.enabled_engines if name in available_engines]
        if request.site:
            base = ENGINE_GROUPS["site"] or ENGINE_GROUPS["general"]
            return [name for name in base if name in available_engines]
        category = request.category if request.category != "auto" else self.infer_category(request.query)
        return self._build_route_engines(category, available_engines, request)

    def fallback_engines(self, request: SearchRequest, used_engines: list[str], available_engines: set[str]) -> list[str]:
        category = request.category if request.category != "auto" else self.infer_category(request.query)
        candidates = self._build_route_engines(category, available_engines, request)
        if category == "general":
            candidates = self._merge(candidates, ["wikipedia", "stackoverflow", "github"])
        return [name for name in candidates if name in available_engines and name not in used_engines]

    def _build_route_engines(self, category: str, available_engines: set[str], request: SearchRequest) -> list[str]:
        selected = [name for name in ENGINE_GROUPS["general"] if name in available_engines]
        for group_name in ROUTE_SPECIALIZED_GROUPS.get(category, []):
            selected = self._merge(selected, [name for name in ENGINE_GROUPS.get(group_name, []) if name in available_engines])
        return self._append_rule_engines(request, selected, available_engines, category=category)

    def _append_rule_engines(self, request: SearchRequest, engine_names: list[str], available_engines: set[str], *, category: str) -> list[str]:
        lowered = request.query.lower()
        extended = list(engine_names)
        if category == "reference" and "wikipedia" in available_engines:
            self._push(extended, "wikipedia")
        if category == "academic" or ACADEMIC_HINT_RE.search(lowered):
            self._push(extended, "arxiv")
        if category == "code" or CODE_HINT_RE.search(lowered):
            self._push(extended, "github")
            self._push(extended, "stackoverflow")
        if category == "news" or NEWS_HINT_RE.search(lowered):
            self._push(extended, "google_news_rss")
        return [name for name in extended if name in available_engines]

    def _push(self, engine_names: list[str], name: str) -> None:
        if name not in engine_names:
            engine_names.append(name)

    def _merge(self, base: list[str], extra: list[str]) -> list[str]:
        merged = list(base)
        for name in extra:
            if name not in merged:
                merged.append(name)
        return merged


class LLMPlanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.last_error: str = ""

    def is_enabled(self) -> bool:
        return bool(self.settings.llm_planner_enabled and self.settings.llm_api_key and self.settings.llm_model)

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
        reason = str(payload.get("reason") or "")
        return PlannerDecision(engines=[], normalized_query=normalized_query, category=category, used_llm=True, reason=reason)

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
            "Return strict JSON only. You plan web search. Clean the query for search quality. "
            "Choose the best route category for the query. Do not choose engines directly. "
            "The runtime will always attach a fixed multi-engine route for the chosen category."
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
            self.last_error = "" if parsed is not None else "invalid_llm_json"
            return parsed
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            self.last_error = "invalid_llm_payload"
            return None

    def _parse_json(self, content: str) -> dict[str, object] | None:
        content = content.strip()
        if not content:
            return None
        match = JSON_BLOCK_RE.search(content)
        content = match.group(1) if match else self._extract_json_object(content)
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
                        fragments = [str(item.get("text")) for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)]
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
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        fragments.append(str(block["text"]))
            if fragments:
                return "".join(fragments)
        return ""
