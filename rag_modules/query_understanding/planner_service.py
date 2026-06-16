"""Two-mode planner service backed by shared query semantics."""

from __future__ import annotations

import logging
from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
import threading

from ..query_constraints import QueryConstraints, loads_json_object
from ..query_policy import get_planner_prompt_template
from ..retrieval.runtime_profile import QueryPlannerRuntimeSettings, QuerySemanticRuntimeSettings
from .features import fallback_entity_phrases, fallback_keywords, normalize_graph_sources
from .graph_intent import infer_graph_max_depth, infer_query_semantic_profile
from .planner_models import QueryPlan
from .registry import (
    GRAPH_QUERY_TYPES,
    GRAPH_RELATION_TYPES,
    GRAPH_ROUTING_STRATEGIES,
    QuerySemanticProfile,
)
from .scoring import (
    estimate_query_complexity,
    estimate_relationship_intensity,
    should_use_fast_rule_plan,
)

logger = logging.getLogger(__name__)

_VALID_STRATEGIES = set(GRAPH_ROUTING_STRATEGIES)
_VALID_GRAPH_QUERY_TYPES = set(GRAPH_QUERY_TYPES)


class QueryPlanner:
    def __init__(
        self,
        llm_client,
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
        self._cache: "OrderedDict[str, QueryPlan]" = OrderedDict()
        self._cache_lock = threading.Lock()
        self._inflight: dict[str, Future[QueryPlan]] = {}

    def plan(self, query: str) -> QueryPlan:
        cache_key = (query or "").strip()
        cached = self._cached_plan(cache_key)
        if cached is not None:
            cached.used_cache = True
            logger.info("Query plan cache hit: %s", cache_key)
            return cached

        future, is_owner = self._claim_planning(cache_key)
        if not is_owner:
            plan = deepcopy(future.result())
            plan.used_cache = True
            logger.info("Query planning joined in-flight request: %s", cache_key)
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
            response = self.llm_client.chat.completions.create(
                model=self.settings.model_name,
                messages=[{"role": "user", "content": self._build_planning_prompt(query)}],
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
                timeout=self.settings.timeout_seconds,
            )
            plan = QueryPlan.from_dict(
                query,
                loads_json_object(response.choices[0].message.content),
                semantic_settings=self.semantic_settings,
            )
            self._calibrate_plan(plan)
            plan.planner_mode = "llm"
            plan.used_cache = False
            logger.info("Query plan created: %s", plan.to_dict())
            return plan
        except Exception as exc:
            logger.warning("Query planning failed, using rule fallback: %s", exc)
            plan = self.rule_based_plan(query)
            self._calibrate_plan(plan)
            plan.fallback_reason = str(exc)
            plan.planner_mode = "fallback_rule"
            plan.used_cache = False
            return plan

    def _build_planning_prompt(self, query: str) -> str:
        graph_query_types_text = "\n".join(f"- {item}" for item in GRAPH_QUERY_TYPES)
        relation_types_text = "\n".join(f"- {item}" for item in GRAPH_RELATION_TYPES)
        preferred_relation_types_text = "\n".join(
            f"- {item}"
            for item in GRAPH_RELATION_TYPES
            if item not in {"REQUIRES", "BELONGS_TO_CATEGORY", "CONTAINS_STEP"}
        )
        return get_planner_prompt_template().format(
            graph_query_types_text=graph_query_types_text,
            relation_types_text=relation_types_text,
            preferred_relation_types_text=preferred_relation_types_text,
            query=query,
        )

    def _remember(self, cache_key: str, plan: QueryPlan) -> None:
        if not self.settings.cache_size or not cache_key:
            return
        snapshot = deepcopy(plan)
        snapshot.used_cache = False
        with self._cache_lock:
            self._cache[cache_key] = snapshot
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self.settings.cache_size:
                self._cache.popitem(last=False)

    def _cached_plan(self, cache_key: str) -> QueryPlan | None:
        if not self.settings.cache_size or not cache_key:
            return None
        with self._cache_lock:
            plan = self._cache.get(cache_key)
            if plan is None:
                return None
            self._cache.move_to_end(cache_key)
            return deepcopy(plan)

    def _claim_planning(self, cache_key: str) -> tuple[Future[QueryPlan], bool]:
        if not cache_key:
            return Future(), True
        with self._cache_lock:
            future = self._inflight.get(cache_key)
            if future is not None:
                return future, False
            future = Future()
            self._inflight[cache_key] = future
            return future, True

    def _release_planning(
        self,
        cache_key: str,
        future: Future[QueryPlan],
    ) -> None:
        if not cache_key:
            return
        with self._cache_lock:
            if self._inflight.get(cache_key) is future:
                self._inflight.pop(cache_key, None)

    def _should_use_fast_rule_plan(self, query: str) -> bool:
        return should_use_fast_rule_plan(query, settings=self.semantic_settings)

    def _has_meaningful_constraints(
        self,
        constraints: QueryConstraints,
        profile: QuerySemanticProfile,
    ) -> bool:
        return bool(
            profile.needs_recipe_recommendation
            or constraints.needs_recipe_recommendation
            or constraints.ingredients
            or constraints.excluded_ingredients
            or constraints.include_terms
            or constraints.exclude_terms
            or constraints.cuisine_terms
            or constraints.excluded_cuisine_terms
            or constraints.category_terms
            or constraints.health_terms
            or constraints.preference_terms
            or constraints.max_total_minutes is not None
            or constraints.max_prep_minutes is not None
            or constraints.max_cook_minutes is not None
        )

    def _is_graph_first_profile(self, profile: QuerySemanticProfile) -> bool:
        if profile.query_type in {"path_finding", "subgraph", "clustering"}:
            return True
        if profile.query_type != "multi_hop":
            return False
        return bool(
            len(profile.relation_hits or []) >= 2
            or len(profile.structural_hits or []) >= 2
            or profile.relationship_intensity >= self.semantic_settings.multi_hop_hint_relationship_threshold
        )

    def _resolve_strategy(
        self,
        *,
        current_strategy: str,
        profile: QuerySemanticProfile,
        constraints: QueryConstraints,
        complexity: float,
        relationship_intensity: float,
    ) -> str:
        settings = self.semantic_settings
        meaningful_constraints = self._has_meaningful_constraints(constraints, profile)
        graph_first = self._is_graph_first_profile(profile)

        if graph_first:
            return "combined" if meaningful_constraints else "graph_rag"

        if relationship_intensity >= settings.high_relationship_routing_threshold:
            if meaningful_constraints and (
                relationship_intensity >= settings.combined_strategy_relationship_threshold
                or complexity >= settings.combined_strategy_complexity_threshold
            ):
                return "combined"
            return "graph_rag"

        if current_strategy == "combined" and not meaningful_constraints:
            return "hybrid_traditional"

        if current_strategy in _VALID_STRATEGIES:
            return current_strategy
        return "combined" if meaningful_constraints else "hybrid_traditional"

    def _resolve_graph_query_type(self, current_type: str, profile: QuerySemanticProfile) -> str:
        if profile.query_type in {"path_finding", "subgraph", "clustering"}:
            return profile.query_type
        if (
            profile.query_type == "multi_hop"
            and current_type == "subgraph"
            and profile.relationship_intensity >= self.semantic_settings.multi_hop_hint_relationship_threshold
        ):
            return "multi_hop"
        if current_type in _VALID_GRAPH_QUERY_TYPES:
            return current_type
        return profile.query_type if profile.query_type in _VALID_GRAPH_QUERY_TYPES else "subgraph"

    def _calibrate_plan(self, plan: QueryPlan) -> None:
        query = plan.query or ""
        profile = infer_query_semantic_profile(query, settings=self.semantic_settings)
        plan.semantic_profile = profile
        settings = self.semantic_settings

        plan.complexity = max(plan.complexity, profile.complexity)
        plan.relationship_intensity = max(plan.relationship_intensity, profile.relationship_intensity)
        plan.reasoning_required = bool(
            plan.reasoning_required
            or profile.reasoning_required
            or plan.complexity >= settings.reasoning_complexity_threshold
            or plan.relationship_intensity >= settings.reasoning_relationship_threshold
        )
        plan.constraints.needs_recipe_recommendation = bool(
            plan.constraints.needs_recipe_recommendation or profile.needs_recipe_recommendation
        )

        resolved_strategy = self._resolve_strategy(
            current_strategy=plan.strategy,
            profile=profile,
            constraints=plan.constraints,
            complexity=plan.complexity,
            relationship_intensity=plan.relationship_intensity,
        )
        if resolved_strategy != plan.strategy:
            plan.validation_errors.append(f"calibrated_strategy:{plan.strategy}->{resolved_strategy}")
            plan.strategy = resolved_strategy

        resolved_query_type = self._resolve_graph_query_type(plan.graph_query_type, profile)
        if resolved_query_type != plan.graph_query_type:
            plan.validation_errors.append(
                f"calibrated_graph_query_type:{plan.graph_query_type}->{resolved_query_type}"
            )
            plan.graph_query_type = resolved_query_type

        for relation_type in profile.relation_types:
            if relation_type not in plan.relation_types:
                plan.relation_types.append(relation_type)

        if not plan.entity_keywords:
            plan.entity_keywords = list(profile.entity_keywords[: settings.entity_keyword_limit])
        if not plan.topic_keywords:
            plan.topic_keywords = list(profile.topic_keywords[: settings.topic_keyword_limit])
        if not plan.target_entities:
            plan.target_entities = list(profile.target_entities[: settings.target_entity_limit])

        if plan.strategy in {"graph_rag", "combined"} and not plan.source_entities:
            fallback_candidates = (
                profile.source_entities
                or fallback_entity_phrases(query)
                or profile.entity_keywords
                or fallback_keywords(query)
            )
            plan.source_entities = normalize_graph_sources(
                fallback_candidates[: settings.source_entity_limit]
            )
            if plan.source_entities:
                plan.validation_errors.append("calibrated_source_entities")

        plan.max_depth = max(
            1,
            min(
                int(
                    plan.max_depth
                    or infer_graph_max_depth(
                        plan.graph_query_type,
                        plan.relationship_intensity,
                        settings=self.semantic_settings,
                    )
                ),
                settings.graph_query_max_depth_cap,
            ),
        )

    def rule_based_plan(self, query: str) -> QueryPlan:
        profile = infer_query_semantic_profile(query, settings=self.semantic_settings)
        constraints = QueryConstraints.from_dict(profile.constraints)
        complexity = max(
            profile.complexity,
            estimate_query_complexity(query, settings=self.semantic_settings),
        )
        relationship_intensity = max(
            profile.relationship_intensity,
            estimate_relationship_intensity(query, settings=self.semantic_settings),
        )
        settings = self.semantic_settings

        strategy = self._resolve_strategy(
            current_strategy="hybrid_traditional",
            profile=profile,
            constraints=constraints,
            complexity=complexity,
            relationship_intensity=relationship_intensity,
        )

        source_candidates = (
            profile.source_entities
            if relationship_intensity >= settings.source_entity_seed_relationship_threshold
            else []
        )
        if not source_candidates and (
            strategy != "hybrid_traditional"
            or relationship_intensity >= settings.source_entity_backfill_relationship_threshold
        ):
            source_candidates = profile.source_entities or profile.entity_keywords or fallback_keywords(query)
        source_entities = normalize_graph_sources(source_candidates[: settings.source_entity_limit])
        if (
            strategy == "hybrid_traditional"
            and relationship_intensity < settings.source_entity_seed_relationship_threshold
        ):
            source_entities = []

        return QueryPlan(
            query=query,
            intent="recommendation" if profile.needs_recipe_recommendation else "qa",
            complexity=complexity,
            relationship_intensity=relationship_intensity,
            reasoning_required=(
                profile.reasoning_required
                or relationship_intensity >= settings.source_entity_seed_relationship_threshold
            ),
            strategy=strategy,
            confidence=settings.rule_fallback_confidence,
            reasoning="LLM planning unavailable; used shared lexical fallback.",
            entity_keywords=profile.entity_keywords[: settings.entity_keyword_limit],
            topic_keywords=profile.topic_keywords[: settings.topic_keyword_limit],
            graph_query_type=profile.query_type,
            source_entities=source_entities[: settings.source_entity_limit],
            target_entities=profile.target_entities[: settings.target_entity_limit],
            relation_types=profile.relation_types,
            max_depth=infer_graph_max_depth(
                profile.query_type,
                relationship_intensity,
                settings=self.semantic_settings,
            ),
            constraints=constraints,
            needs_recipe_recommendation=profile.needs_recipe_recommendation,
            fallback_reason="rule_based",
            planner_mode="rule_based",
            semantic_profile=profile,
        )


__all__ = ["QueryPlanner"]

