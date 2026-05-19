from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings
from app.search.engine_config import load_engine_config
from app.search.llm_planner import LLMPlanner, PlannerDecision
from app.search.types import SearchRequest


NEWS_HINT_RE = re.compile(r"\b(latest|recent|today|news|headline|breaking)\b", re.I)
ACADEMIC_HINT_RE = re.compile(r"\b(paper|survey|benchmark|arxiv|research)\b", re.I)
CODE_HINT_RE = re.compile(r"\b(github|repo|repository|issue|sdk|library|debug|bug|error|exception)\b", re.I)
REFERENCE_HINT_RE = re.compile(r"\b(who is|what is|history|biography|definition|wiki)\b", re.I)
@dataclass(slots=True)
class EngineGroups:
    groups: dict[str, list[str]]
    disabled: set[str]

    def get(self, key: str) -> list[str]:
        return [name for name in self.groups.get(key, []) if name not in self.disabled]


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

    def load_engine_groups(self, config_path: str | None = None) -> EngineGroups:
        config = load_engine_config(config_path or self.settings.search_engine_config_path)
        return EngineGroups(groups=config.groups, disabled=config.disabled)

    def plan_decision(self, request: SearchRequest, available_engines: set[str]) -> PlannerDecision:
        groups = self.load_engine_groups(request.engine_config_path)
        allowed_engines = [name for name in sorted(available_engines) if name not in groups.disabled]
        default_category = request.category if request.category != "auto" else self.infer_category(request.query)
        if not request.enabled_engines:
            llm_decision = self.llm_planner.plan(
                request,
                available_engines=allowed_engines,
                engine_groups=groups.groups,
                default_category=default_category,
            )
            if llm_decision is not None:
                return llm_decision
        return PlannerDecision(
            engines=self.plan(request, available_engines),
            normalized_query=request.query.strip(),
            category=default_category,
            used_llm=False,
            reason=f"rule_planner ({self.llm_planner.last_error})" if self.llm_planner.last_error else "rule_planner",
        )

    def plan(self, request: SearchRequest, available_engines: set[str]) -> list[str]:
        groups = self.load_engine_groups(request.engine_config_path)
        if request.enabled_engines:
            return [name for name in request.enabled_engines if name in available_engines and name not in groups.disabled]
        if request.site:
            base = groups.get("site") or groups.get("general")
            return [name for name in base if name in available_engines]

        group_name = request.category if request.category != "auto" else self.infer_category(request.query)
        selected = [name for name in groups.get("general") if name in available_engines]
        if group_name != "general":
            selected = self._merge(selected, [name for name in groups.get(group_name) if name in available_engines])
        return self._append_rule_engines(request, selected, available_engines, category=group_name)

    def fallback_engines(self, request: SearchRequest, used_engines: list[str], available_engines: set[str]) -> list[str]:
        groups = self.load_engine_groups(request.engine_config_path)
        if request.category == "general":
            candidates = ["wikipedia", "stackoverflow", "github"]
        elif request.category == "code":
            candidates = ["stackoverflow", "github", "duckduckgo_lite"]
        elif request.category == "academic":
            candidates = ["arxiv", "duckduckgo_lite"]
        elif request.category == "reference":
            candidates = ["wikipedia", "duckduckgo_lite"]
        elif request.category == "news":
            candidates = ["google_news_rss", "duckduckgo_lite"]
        else:
            candidates = groups.get("general")
        return [name for name in candidates if name in available_engines and name not in used_engines and name not in groups.disabled]

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
