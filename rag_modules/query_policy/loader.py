"""Load versioned query policy bundles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from string import Formatter
from typing import cast

from .models import PolicyLoadError, PolicyMetadata, PromptTemplates, QueryPolicyBundle
from .parsers import (
    parse_generation,
    parse_graph,
    parse_lexicon,
    parse_relations,
    parse_routing,
    parse_runtime_defaults,
    parse_scoring,
)
from .parsers.common import mapping

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


def _read_json(path: Path, root: Path) -> dict[str, object]:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload: object = json.load(file)
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
    raw_items = cast(Mapping[object, object], payload)
    return {str(key): value for key, value in raw_items.items()}


def _hash_payload(payload: Mapping[str, object]) -> str:
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


def _verify_manifest(manifest: Mapping[str, object], root: Path) -> None:
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


def _read_prompts(manifest: Mapping[str, object], root: Path) -> dict[str, str]:
    prompts = mapping(manifest.get("prompts"), root, "prompts")
    texts: dict[str, str] = {}
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


def _to_metadata(
    manifest: Mapping[str, object],
    policy_payload: Mapping[str, object],
    prompt_texts: Mapping[str, str],
) -> PolicyMetadata:
    return PolicyMetadata(
        schema_version=str(manifest["schema_version"]),
        policy_version=str(manifest["policy_version"]),
        prompt_version=str(manifest["prompt_version"]),
        policy_hash=_hash_payload(policy_payload),
        prompt_hash=_hash_texts(prompt_texts),
        bundle_name=str(manifest["name"]),
    )


@lru_cache(maxsize=8)
def load_policy_bundle(bundle_path: str | Path | None = None) -> QueryPolicyBundle:
    root = Path(bundle_path) if bundle_path is not None else default_policy_bundle_path()
    manifest = _read_json(root / "manifest.json", root)
    _verify_manifest(manifest, root)

    policy_payload = _read_json(root / str(manifest["policy_path"]), root)
    prompt_texts = _read_prompts(manifest, root)
    graph = parse_graph(policy_payload, root)

    return QueryPolicyBundle(
        metadata=_to_metadata(manifest, policy_payload, prompt_texts),
        lexicon=parse_lexicon(policy_payload, root),
        relations=parse_relations(policy_payload, root, graph_reasoning=graph.reasoning),
        scoring=parse_scoring(policy_payload, root),
        routing=parse_routing(policy_payload, root),
        graph=graph,
        generation=parse_generation(policy_payload, root),
        runtime_defaults=parse_runtime_defaults(policy_payload.get("runtime_defaults"), root),
        prompts=PromptTemplates(
            query_planner=prompt_texts["query_planner"],
            answer_plan=prompt_texts["answer_plan"],
            answer_compose=prompt_texts["answer_compose"],
            answer_direct=prompt_texts["answer_direct"],
        ),
    )


def get_query_policy(bundle_path: str | Path | None = None) -> QueryPolicyBundle:
    return load_policy_bundle(bundle_path)
