"""Two-mode planner service backed by shared query semantics."""

from __future__ import annotations

import logging
from concurrent.futures import Future
from copy import deepcopy

from ...contracts import (
    QueryPlan,
    QueryPlannerRuntimeSettings,
    QuerySemanticProfile,
    QuerySemanticRuntimeSettings,
)
from ...domain.shared.query_constraints import QueryConstraints, loads_json_object
from ...runtime_contracts import LLMClientPort
from ...safe_logging import log_failure
from ..scoring import should_use_fast_rule_plan
from .cache import QueryPlannerCache
from .calibration import QueryPlanCalibrator
from .prompting import build_planning_prompt, response_text
from .rule_based import RuleBasedPlanner

logger = logging.getLogger(__name__)


class QueryPlanner:
    def __init__(
        self,
        llm_client: LLMClientPort | None,
        model_name: str | None = None,
        cache_size: int | None = None,
        timeout_seconds: int | None = None,
        fast_rule_planning: bool | None = None,
        settings: QueryPlannerRuntimeSettings | None = None,
        semantic_settings: QuerySemanticRuntimeSettings | None = None,
    ):
        self.llm_client = llm_client
        if settings is None:
            settings = QueryPlannerRuntimeSettings(
                model_name=model_name or "qwen3.7-plus",
                cache_size=128 if cache_size is None else cache_size,
                timeout_seconds=20 if timeout_seconds is None else timeout_seconds,
                fast_rule_planning=True if fast_rule_planning is None else fast_rule_planning,
            )
        self.settings = settings
        self.semantic_settings = semantic_settings or QuerySemanticRuntimeSettings()
        self._plan_cache = QueryPlannerCache()
        self._calibrator = QueryPlanCalibrator(self.semantic_settings)
        self._rule_planner = RuleBasedPlanner(self.semantic_settings, self._calibrator)

    def plan(self, query: str) -> QueryPlan:
        cache_key = (query or "").strip()
        cached = self._cached_plan(cache_key)
        if cached is not None:
            cached.used_cache = True
            logger.info("Query plan cache hit")
            return cached

        future, is_owner = self._claim_planning(cache_key)
        if not is_owner:
            plan = deepcopy(future.result())
            plan.used_cache = True
            logger.info("Query planning joined in-flight request")
            return plan

        try:
            plan = self._create_plan(query, cache_key=cache_key)
            self._remember(cache_key, plan)
            future.set_result(deepcopy(plan))
            return plan
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            self._release_planning(cache_key, future)

    def _create_plan(self, query: str, *, cache_key: str) -> QueryPlan:
        if self.settings.fast_rule_planning and self._should_use_fast_rule_plan(cache_key):
            plan = self.rule_based_plan(query)
            self._calibrate_plan(plan)
            plan.fallback_reason = "fast_rule"
            plan.planner_mode = "fast_rule"
            plan.used_cache = False
            return plan

        try:
            if self.llm_client is None:
                raise RuntimeError("No LLM client configured for query planning.")
            response = self.llm_client.create_completion(
                prompt=self._build_planning_prompt(query),
                model_name=self.settings.model_name,
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
                timeout=self.settings.timeout_seconds,
            )
            response_content = self._response_text(response) or "{}"
            plan = QueryPlan.from_dict(
                query,
                loads_json_object(response_content),
                semantic_settings=self.semantic_settings,
            )
            self._calibrate_plan(plan)
            plan.planner_mode = "llm"
            plan.used_cache = False
            planner_mode = plan.planner_mode
            strategy = plan.strategy
            logger.info("Query plan created: mode=%s strategy=%s", planner_mode, strategy)
            return plan
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "query_planning_failed",
                code="QUERY_PROCESSING_FAILED",
                error=exc,
            )
            plan = self.rule_based_plan(query)
            self._calibrate_plan(plan)
            plan.fallback_reason = "query_planning_failed"
            plan.planner_mode = "fallback_rule"
            plan.used_cache = False
            return plan

    def _build_planning_prompt(self, query: str) -> str:
        return build_planning_prompt(query)

    @staticmethod
    def _response_text(response: object) -> str:
        return response_text(response)

    def _remember(self, cache_key: str, plan: QueryPlan) -> None:
        self._plan_cache.remember(cache_key, plan, cache_size=self.settings.cache_size)

    def _cached_plan(self, cache_key: str) -> QueryPlan | None:
        return self._plan_cache.cached_plan(cache_key, cache_size=self.settings.cache_size)

    def _claim_planning(self, cache_key: str) -> tuple[Future[QueryPlan], bool]:
        return self._plan_cache.claim_planning(cache_key)

    def _release_planning(
        self,
        cache_key: str,
        future: Future[QueryPlan],
    ) -> None:
        self._plan_cache.release_planning(cache_key, future)

    def _should_use_fast_rule_plan(self, query: str) -> bool:
        return should_use_fast_rule_plan(query, settings=self.semantic_settings)

    def _has_meaningful_constraints(
        self,
        constraints: QueryConstraints,
        profile: QuerySemanticProfile,
    ) -> bool:
        return self._calibrator.has_meaningful_constraints(constraints, profile)

    def _is_graph_first_profile(self, profile: QuerySemanticProfile) -> bool:
        return self._calibrator.is_graph_first_profile(profile)

    def _resolve_strategy(
        self,
        *,
        current_strategy: str,
        profile: QuerySemanticProfile,
        constraints: QueryConstraints,
        complexity: float,
        relationship_intensity: float,
    ) -> str:
        return self._calibrator.resolve_strategy(
            current_strategy=current_strategy,
            profile=profile,
            constraints=constraints,
            complexity=complexity,
            relationship_intensity=relationship_intensity,
        )

    def _resolve_graph_query_type(self, current_type: str, profile: QuerySemanticProfile) -> str:
        return self._calibrator.resolve_graph_query_type(current_type, profile)

    def _calibrate_plan(self, plan: QueryPlan) -> None:
        self._calibrator.calibrate(plan)

    def rule_based_plan(self, query: str) -> QueryPlan:
        return self._rule_planner.plan(query)


__all__ = ["QueryPlanner"]
