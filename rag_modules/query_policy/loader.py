"""Load versioned query policy bundles."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from string import Formatter
from typing import Any, Dict, Mapping, Tuple

from .models import (
    GenerationPolicy,
    GraphPolicy,
    LexiconPolicy,
    PolicyLoadError,
    PolicyMetadata,
    PromptTemplates,
    QueryPolicyBundle,
    RelationPolicy,
    RoutingPolicy,
    ScoringPolicy,
)

SUPPORTED_SCHEMA_VERSION = "policy-bundle-v1"
DEFAULT_BUNDLE_NAME = "c9-default-v1"

_REQUIRED_PROMPT_VARIABLES = {
    "query_planner": {
        "query",
        "graph_query_types_text",
        "relation_types_text",
        "preferred_relation_types_text",
    },
    "answer_plan": {"question", "evidence_summary"},
    "answer_compose": {"question", "plan_json", "evidence_text"},
    "answer_direct": {"question", "evidence_text"},
}


def default_policy_bundle_path() -> Path:
    return Path(__file__).parent / "resources" / DEFAULT_BUNDLE_NAME


def _to_tuple(value: Any) -> Tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    if value is None:
        return ()
    text = str(value).strip()
    return (text,) if text else ()


def _to_tuple_map(value: Any) -> Dict[str, Tuple[str, ...]]:
    payload = dict(value or {})
    return {str(key): _to_tuple(items) for key, items in payload.items()}


def _to_runtime_defaults(value: Any) -> Dict[str, Dict[str, Any]]:
    payload = dict(value or {})
    return {str(section): dict(section_values or {}) for section, section_values in payload.items()}


def _to_str_map(value: Any) -> Dict[str, str]:
    return {
        str(key): str(item)
        for key, item in dict(value or {}).items()
        if str(key).strip() and str(item).strip()
    }


def _to_float_map(value: Any) -> Dict[str, float]:
    result: Dict[str, float] = {}
    for key, item in dict(value or {}).items():
        try:
            result[str(key)] = float(item)
        except (TypeError, ValueError) as exc:
            raise PolicyLoadError(f"Invalid float value for {key}") from exc
    return result


def _to_int_map(value: Any) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for key, item in dict(value or {}).items():
        try:
            result[str(key)] = int(item)
        except (TypeError, ValueError) as exc:
            raise PolicyLoadError(f"Invalid integer value for {key}") from exc
    return result


def _to_nested_dict_map(value: Any, root: Path, field_path: str) -> Dict[str, Dict[str, Any]]:
    if not isinstance(value, dict):
        raise PolicyLoadError(
            f"Policy field must be an object: {field_path}",
            bundle_path=str(root),
            field_path=field_path,
        )
    result: Dict[str, Dict[str, Any]] = {}
    for key, item in value.items():
        if not isinstance(item, dict):
            raise PolicyLoadError(
                f"Policy field values must be objects: {field_path}",
                bundle_path=str(root),
                field_path=f"{field_path}.{key}",
            )
        result[str(key)] = dict(item)
    return result


def _to_sub_question_items(value: Any, root: Path) -> Tuple[Dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise PolicyLoadError(
            "Policy graph.sub_questions must be a list",
            bundle_path=str(root),
            field_path="graph.sub_questions",
        )
    result: list[Dict[str, Any]] = []
    for index, item in enumerate(value):
        field_path = f"graph.sub_questions[{index}]"
        if not isinstance(item, dict):
            raise PolicyLoadError(
                "Graph sub-question must be an object",
                bundle_path=str(root),
                field_path=field_path,
            )
        sub_question = dict(item)
        sub_question_id = str(sub_question.get("id", "")).strip()
        template = str(sub_question.get("template", "")).strip()
        if not sub_question_id:
            raise PolicyLoadError(
                "Graph sub-question is missing id",
                bundle_path=str(root),
                field_path=f"{field_path}.id",
            )
        if not template:
            raise PolicyLoadError(
                "Graph sub-question is missing template",
                bundle_path=str(root),
                field_path=f"{field_path}.template",
            )
        when = sub_question.get("when", {})
        if when is None:
            when = {}
        if not isinstance(when, dict):
            raise PolicyLoadError(
                "Graph sub-question when must be an object",
                bundle_path=str(root),
                field_path=f"{field_path}.when",
            )
        sub_question["id"] = sub_question_id
        sub_question["template"] = template
        sub_question["when"] = dict(when)
        result.append(sub_question)
    return tuple(result)


def _read_json(path: Path, root: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyLoadError(
            f"Unable to read JSON file: {path.name}",
            bundle_path=str(root),
        ) from exc
    if not isinstance(payload, dict):
        raise PolicyLoadError(
            f"JSON file must contain an object: {path.name}",
            bundle_path=str(root),
        )
    return payload


def _hash_payload(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_texts(texts: Mapping[str, str]) -> str:
    canonical = json.dumps(
        {name: texts[name] for name in sorted(texts)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _required_mapping(payload: Mapping[str, Any], key: str, root: Path) -> Dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise PolicyLoadError(
            f"Policy section must be an object: {key}",
            bundle_path=str(root),
            field_path=key,
        )
    return dict(value)


def _verify_manifest(manifest: Mapping[str, Any], root: Path) -> None:
    schema_version = manifest.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise PolicyLoadError(
            f"Unsupported or missing schema_version: {schema_version!r}",
            bundle_path=str(root),
            field_path="schema_version",
        )
    for field_name in ("policy_version", "prompt_version", "name", "policy_path", "prompts"):
        if field_name not in manifest:
            raise PolicyLoadError(
                f"Missing manifest field: {field_name}",
                bundle_path=str(root),
                field_path=field_name,
            )


def _prompt_variables(template: str) -> set[str]:
    variables: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            variables.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return variables


def _verify_prompt_variables(texts: Mapping[str, str], root: Path) -> None:
    for prompt_name, required_variables in _REQUIRED_PROMPT_VARIABLES.items():
        if prompt_name not in texts:
            raise PolicyLoadError(
                f"Missing prompt template: {prompt_name}",
                bundle_path=str(root),
                field_path=f"prompts.{prompt_name}",
            )
        actual_variables = _prompt_variables(texts[prompt_name])
        missing = sorted(required_variables - actual_variables)
        if missing:
            raise PolicyLoadError(
                f"Prompt {prompt_name} is missing variable: {missing[0]}",
                bundle_path=str(root),
                field_path=f"prompts.{prompt_name}.{missing[0]}",
            )


def _read_prompts(manifest: Mapping[str, Any], root: Path) -> Dict[str, str]:
    prompts = dict(manifest.get("prompts") or {})
    texts: Dict[str, str] = {}
    for prompt_name in _REQUIRED_PROMPT_VARIABLES:
        relative_path = prompts.get(prompt_name)
        if not relative_path:
            raise PolicyLoadError(
                f"Missing prompt path: {prompt_name}",
                bundle_path=str(root),
                field_path=f"prompts.{prompt_name}",
            )
        path = root / str(relative_path)
        try:
            texts[prompt_name] = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PolicyLoadError(
                f"Unable to read prompt file: {relative_path}",
                bundle_path=str(root),
                field_path=f"prompts.{prompt_name}",
            ) from exc
    _verify_prompt_variables(texts, root)
    return texts


def _verify_relation_references(
    relation_types: Tuple[str, ...],
    relation_index_keywords: Mapping[str, Tuple[str, ...]],
    relation_query_markers: Mapping[str, Tuple[str, ...]],
    root: Path,
) -> None:
    known = set(relation_types)
    for field_name, relation_map in (
        ("relations.relation_index_keywords", relation_index_keywords),
        ("relations.relation_query_markers", relation_query_markers),
    ):
        unknown = sorted(set(relation_map) - known)
        if unknown:
            raise PolicyLoadError(
                f"Unknown graph relation type: {unknown[0]}",
                bundle_path=str(root),
                field_path=f"{field_name}.{unknown[0]}",
            )


@lru_cache(maxsize=8)
def load_policy_bundle(bundle_path: str | Path | None = None) -> QueryPolicyBundle:
    root = Path(bundle_path) if bundle_path is not None else default_policy_bundle_path()
    manifest = _read_json(root / "manifest.json", root)
    _verify_manifest(manifest, root)

    policy_payload = _read_json(root / str(manifest["policy_path"]), root)
    prompt_texts = _read_prompts(manifest, root)

    lexicon = _required_mapping(policy_payload, "lexicon", root)
    relation_payload = _required_mapping(policy_payload, "relations", root)
    scoring_payload = _required_mapping(policy_payload, "scoring", root)
    routing_payload = _required_mapping(policy_payload, "routing", root)
    graph_payload = _required_mapping(policy_payload, "graph", root)
    generation_payload = _required_mapping(policy_payload, "generation", root)
    entity_linker = dict(relation_payload.get("entity_linker") or {})

    relation_types = _to_tuple(relation_payload.get("graph_relation_types"))
    relation_index_keywords = _to_tuple_map(relation_payload.get("relation_index_keywords"))
    relation_query_markers = _to_tuple_map(relation_payload.get("relation_query_markers"))
    _verify_relation_references(
        relation_types,
        relation_index_keywords,
        relation_query_markers,
        root,
    )

    metadata = PolicyMetadata(
        schema_version=str(manifest["schema_version"]),
        policy_version=str(manifest["policy_version"]),
        prompt_version=str(manifest["prompt_version"]),
        policy_hash=_hash_payload(policy_payload),
        prompt_hash=_hash_texts(prompt_texts),
        bundle_name=str(manifest["name"]),
    )

    return QueryPolicyBundle(
        metadata=metadata,
        lexicon=LexiconPolicy(
            term_sets=_to_tuple_map(lexicon.get("term_sets")),
            regex_rules=_to_tuple_map(lexicon.get("regex_rules")),
        ),
        relations=RelationPolicy(
            graph_routing_strategies=_to_tuple(relation_payload.get("graph_routing_strategies")),
            graph_query_types=_to_tuple(relation_payload.get("graph_query_types")),
            graph_relation_types=relation_types,
            semantic_relation_hints=_to_str_map(relation_payload.get("semantic_relation_hints")),
            relation_index_keywords=relation_index_keywords,
            relation_query_markers=relation_query_markers,
            entity_linker_preferred_labels=_to_tuple(entity_linker.get("preferred_labels")),
            entity_linker_query_type_priorities=_to_tuple_map(
                entity_linker.get("query_type_priorities")
            ),
            entity_linker_relation_priorities=_to_tuple_map(
                entity_linker.get("relation_priorities")
            ),
        ),
        scoring=ScoringPolicy(
            structural_relationship_factor=float(
                scoring_payload.get("structural_relationship_factor", 0.5)
            ),
            length_norm_chars=int(scoring_payload.get("length_norm_chars", 140)),
            weights=_to_float_map(scoring_payload.get("weights")),
            boosts=_to_float_map(scoring_payload.get("boosts")),
        ),
        routing=RoutingPolicy(
            graph_first_query_types=_to_tuple(routing_payload.get("graph_first_query_types")),
            multi_hop_graph_first_relation_hits=int(
                routing_payload.get("multi_hop_graph_first_relation_hits", 2)
            ),
            meaningful_constraint_fields=_to_tuple(
                routing_payload.get("meaningful_constraint_fields")
            ),
            validation_labels=_to_str_map(routing_payload.get("validation_labels")),
        ),
        graph=GraphPolicy(
            max_depth=_to_int_map(graph_payload.get("max_depth")),
            max_nodes=_to_int_map(graph_payload.get("max_nodes")),
            sub_questions=_to_sub_question_items(graph_payload.get("sub_questions"), root),
        ),
        generation=GenerationPolicy(
            answer_types=_to_nested_dict_map(
                generation_payload.get("answer_types"),
                root,
                "generation.answer_types",
            ),
            relation_explanation_markers=_to_tuple(
                generation_payload.get("relation_explanation_markers")
            ),
            rule_plan=dict(generation_payload.get("rule_plan") or {}),
            decision=dict(generation_payload.get("decision") or {}),
        ),
        runtime_defaults=_to_runtime_defaults(policy_payload.get("runtime_defaults")),
        prompts=PromptTemplates(
            query_planner=prompt_texts["query_planner"],
            answer_plan=prompt_texts["answer_plan"],
            answer_compose=prompt_texts["answer_compose"],
            answer_direct=prompt_texts["answer_direct"],
        ),
    )


def get_query_policy(bundle_path: str | Path | None = None) -> QueryPolicyBundle:
    return load_policy_bundle(bundle_path)


def get_planner_prompt_template() -> str:
    return get_query_policy().prompts.query_planner


def flatten_term_groups(*names: str) -> Tuple[str, ...]:
    policy = get_query_policy()
    merged: list[str] = []
    for name in names:
        merged.extend(policy.lexicon.term_group(name))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in merged:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return tuple(deduped)
