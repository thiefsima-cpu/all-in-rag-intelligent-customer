"""Curated quality evaluation corpus contract and loader."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, List

DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "curated_eval_corpus.json"
)


class EvalResponseMode(StrEnum):
    GROUNDED_ANSWER = "grounded_answer"
    NO_EVIDENCE = "no_evidence"
    CLARIFICATION = "clarification"
    CONSTRAINT_CONFLICT = "constraint_conflict"

    @property
    def is_abstention(self) -> bool:
        return self is not EvalResponseMode.GROUNDED_ANSWER


@dataclass(frozen=True)
class EvalExpectation:
    response_mode: EvalResponseMode
    strategy: str | None
    recipe_names: tuple[str, ...]
    answer_terms: tuple[str, ...]
    recipe_relevance: dict[str, float]


@dataclass(frozen=True)
class OfflineEvidenceFixture:
    recipe_name: str
    content: str
    score: float
    evidence_type: str


@dataclass(frozen=True)
class OfflineEvalFixture:
    strategy: str
    answer: str
    evidence: tuple[OfflineEvidenceFixture, ...]


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    query: str
    category: str
    dimensions: tuple[str, ...]
    expectation: EvalExpectation
    offline_fixture: OfflineEvalFixture


_ROOT_KEYS = frozenset({"id", "query", "category", "dimensions", "expectation", "offline_fixture"})
_EXPECTATION_KEYS = frozenset(
    {"response_mode", "strategy", "recipe_names", "answer_terms", "recipe_relevance"}
)
_OFFLINE_FIXTURE_KEYS = frozenset({"strategy", "answer", "evidence"})
_EVIDENCE_KEYS = frozenset({"recipe_name", "content", "score", "evidence_type"})


def _case_context(corpus_path: Path, index: int, case_id: str | None = None) -> str:
    context = f"Eval corpus at {corpus_path}, case[{index}]"
    if case_id:
        context += f" id={case_id!r}"
    return context


def _validation_error(
    corpus_path: Path,
    index: int,
    case_id: str | None,
    message: str,
) -> ValueError:
    return ValueError(f"{_case_context(corpus_path, index, case_id)}: {message}")


def _require_object(
    value: object,
    *,
    corpus_path: Path,
    index: int,
    case_id: str | None,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            f"{field_name} must be a JSON object",
        )
    return value


def _require_exact_keys(
    value: dict[str, Any],
    allowed_keys: frozenset[str],
    *,
    corpus_path: Path,
    index: int,
    case_id: str | None,
    field_name: str,
) -> None:
    keys = set(value)
    unknown = sorted(keys - allowed_keys)
    missing = sorted(allowed_keys - keys)
    if unknown:
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            f"{field_name} contains unknown keys: {unknown}",
        )
    if missing:
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            f"{field_name} is missing required keys: {missing}",
        )


def _require_string(
    value: object,
    *,
    corpus_path: Path,
    index: int,
    case_id: str | None,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            f"{field_name} must be a non-empty string",
        )
    return value.strip()


def _require_optional_string(
    value: object,
    *,
    corpus_path: Path,
    index: int,
    case_id: str | None,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _require_string(
        value,
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
        field_name=field_name,
    )


def _require_string_tuple(
    value: object,
    *,
    corpus_path: Path,
    index: int,
    case_id: str | None,
    field_name: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            f"{field_name} must be a JSON list",
        )
    return tuple(
        _require_string(
            item,
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name=f"{field_name}[{item_index}]",
        )
        for item_index, item in enumerate(value)
    )


def _require_nonnegative_number(
    value: object,
    *,
    corpus_path: Path,
    index: int,
    case_id: str | None,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            f"{field_name} must be a number, not a boolean",
        )
    if not isinstance(value, (int, float)):
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            f"{field_name} must be a number; got {type(value).__name__}",
        )
    try:
        number = float(value)
    except OverflowError as error:
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            f"{field_name} must be finite and non-negative",
        ) from error
    if not math.isfinite(number) or number < 0:
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            f"{field_name} must be finite and non-negative",
        )
    return number


def _parse_recipe_relevance(
    value: object,
    *,
    corpus_path: Path,
    index: int,
    case_id: str,
) -> dict[str, float]:
    relevance = _require_object(
        value,
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
        field_name="expectation.recipe_relevance",
    )
    parsed: dict[str, float] = {}
    for recipe_name, grade in relevance.items():
        name = _require_string(
            recipe_name,
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name="expectation.recipe_relevance key",
        )
        if name in parsed:
            raise _validation_error(
                corpus_path,
                index,
                case_id,
                "expectation.recipe_relevance contains a normalized key collision: "
                f"{recipe_name!r} normalizes to {name!r}",
            )
        parsed[name] = _require_nonnegative_number(
            grade,
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name=f"expectation.recipe_relevance[{name!r}]",
        )
    if parsed and not any(grade > 0 for grade in parsed.values()):
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            "expectation.recipe_relevance must contain at least one positive grade",
        )
    return parsed


def _parse_expectation(
    value: object,
    *,
    corpus_path: Path,
    index: int,
    case_id: str,
) -> EvalExpectation:
    payload = _require_object(
        value,
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
        field_name="expectation",
    )
    _require_exact_keys(
        payload,
        _EXPECTATION_KEYS,
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
        field_name="expectation",
    )
    response_mode_value = _require_string(
        payload["response_mode"],
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
        field_name="expectation.response_mode",
    )
    try:
        response_mode = EvalResponseMode(response_mode_value)
    except ValueError as error:
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            f"expectation.response_mode is unknown: {response_mode_value!r}",
        ) from error
    return EvalExpectation(
        response_mode=response_mode,
        strategy=_require_optional_string(
            payload["strategy"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name="expectation.strategy",
        ),
        recipe_names=_require_string_tuple(
            payload["recipe_names"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name="expectation.recipe_names",
        ),
        answer_terms=_require_string_tuple(
            payload["answer_terms"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name="expectation.answer_terms",
        ),
        recipe_relevance=_parse_recipe_relevance(
            payload["recipe_relevance"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
        ),
    )


def _parse_evidence_fixture(
    value: object,
    *,
    corpus_path: Path,
    index: int,
    case_id: str,
    evidence_index: int,
) -> OfflineEvidenceFixture:
    field_name = f"offline_fixture.evidence[{evidence_index}]"
    payload = _require_object(
        value,
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
        field_name=field_name,
    )
    _require_exact_keys(
        payload,
        _EVIDENCE_KEYS,
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
        field_name=field_name,
    )
    return OfflineEvidenceFixture(
        recipe_name=_require_string(
            payload["recipe_name"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name=f"{field_name}.recipe_name",
        ),
        content=_require_string(
            payload["content"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name=f"{field_name}.content",
        ),
        score=_require_nonnegative_number(
            payload["score"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name=f"{field_name}.score",
        ),
        evidence_type=_require_string(
            payload["evidence_type"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name=f"{field_name}.evidence_type",
        ),
    )


def _parse_offline_fixture(
    value: object,
    *,
    corpus_path: Path,
    index: int,
    case_id: str,
) -> OfflineEvalFixture:
    payload = _require_object(
        value,
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
        field_name="offline_fixture",
    )
    _require_exact_keys(
        payload,
        _OFFLINE_FIXTURE_KEYS,
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
        field_name="offline_fixture",
    )
    evidence_payload = payload["evidence"]
    if not isinstance(evidence_payload, list):
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            "offline_fixture.evidence must be a JSON list",
        )
    return OfflineEvalFixture(
        strategy=_require_string(
            payload["strategy"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name="offline_fixture.strategy",
        ),
        answer=_require_string(
            payload["answer"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name="offline_fixture.answer",
        ),
        evidence=tuple(
            _parse_evidence_fixture(
                item,
                corpus_path=corpus_path,
                index=index,
                case_id=case_id,
                evidence_index=evidence_index,
            )
            for evidence_index, item in enumerate(evidence_payload)
        ),
    )


def _parse_eval_case(payload: dict[str, Any], *, corpus_path: Path, index: int) -> EvalCase:
    raw_case_id = payload["id"] if "id" in payload else None
    context_case_id = raw_case_id.strip() if isinstance(raw_case_id, str) else None
    legacy_keys = sorted(key for key in payload if key.startswith("expected_"))
    if legacy_keys:
        raise _validation_error(
            corpus_path,
            index,
            context_case_id,
            f"legacy fields are not allowed: {legacy_keys}",
        )
    _require_exact_keys(
        payload,
        _ROOT_KEYS,
        corpus_path=corpus_path,
        index=index,
        case_id=context_case_id,
        field_name="case",
    )
    case_id = _require_string(
        payload["id"],
        corpus_path=corpus_path,
        index=index,
        case_id=context_case_id,
        field_name="id",
    )
    dimensions = _require_string_tuple(
        payload["dimensions"],
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
        field_name="dimensions",
    )
    if not dimensions:
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            "dimensions must be a non-empty list",
        )
    if len(set(dimensions)) != len(dimensions):
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            "dimensions must not contain duplicates",
        )
    expectation = _parse_expectation(
        payload["expectation"],
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
    )
    offline_fixture = _parse_offline_fixture(
        payload["offline_fixture"],
        corpus_path=corpus_path,
        index=index,
        case_id=case_id,
    )
    if expectation.strategy is not None and offline_fixture.strategy != expectation.strategy:
        raise _validation_error(
            corpus_path,
            index,
            case_id,
            "offline_fixture.strategy must match expectation.strategy",
        )
    if expectation.response_mode.is_abstention:
        if expectation.recipe_names:
            raise _validation_error(
                corpus_path,
                index,
                case_id,
                "abstention expectation must not contain recipe_names",
            )
        if expectation.recipe_relevance:
            raise _validation_error(
                corpus_path,
                index,
                case_id,
                "abstention expectation must not contain recipe_relevance",
            )
        if offline_fixture.evidence:
            raise _validation_error(
                corpus_path,
                index,
                case_id,
                "abstention offline_fixture must not contain evidence",
            )
    else:
        if not offline_fixture.evidence:
            raise _validation_error(
                corpus_path,
                index,
                case_id,
                "grounded_answer offline_fixture must contain evidence",
            )
        fixture_recipe_names = {item.recipe_name for item in offline_fixture.evidence}
        positive_relevance_names = {
            name for name, grade in expectation.recipe_relevance.items() if grade > 0
        }
        expected_recipe_names = set(expectation.recipe_names) | positive_relevance_names
        missing_recipe_names = sorted(expected_recipe_names - fixture_recipe_names)
        if missing_recipe_names:
            raise _validation_error(
                corpus_path,
                index,
                case_id,
                "grounded expected recipes are absent from offline_fixture.evidence: "
                f"{missing_recipe_names}",
            )
    return EvalCase(
        case_id=case_id,
        query=_require_string(
            payload["query"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name="query",
        ),
        category=_require_string(
            payload["category"],
            corpus_path=corpus_path,
            index=index,
            case_id=case_id,
            field_name="category",
        ),
        dimensions=dimensions,
        expectation=expectation,
        offline_fixture=offline_fixture,
    )


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, Any]], *, corpus_path: Path
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"Eval corpus at {corpus_path}: duplicate JSON object key {key!r}")
        payload[key] = value
    return payload


def load_eval_cases(path: str | Path = DEFAULT_CORPUS_PATH) -> List[EvalCase]:
    corpus_path = Path(path).resolve()
    try:
        with corpus_path.open("r", encoding="utf-8") as file:
            payload = json.load(
                file,
                object_pairs_hook=lambda pairs: _reject_duplicate_json_keys(
                    pairs, corpus_path=corpus_path
                ),
            )
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Eval corpus at {corpus_path}: invalid JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error
    if not isinstance(payload, list):
        raise ValueError(f"Eval corpus at {corpus_path}, case[?]: corpus must be a JSON list")
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(payload):
        item = _require_object(
            item,
            corpus_path=corpus_path,
            index=index,
            case_id=None,
            field_name="case",
        )
        case = _parse_eval_case(item, corpus_path=corpus_path, index=index)
        if case.case_id in seen_ids:
            raise _validation_error(
                corpus_path,
                index,
                case.case_id,
                "duplicate case id",
            )
        seen_ids.add(case.case_id)
        cases.append(case)
    return cases


__all__ = [
    "DEFAULT_CORPUS_PATH",
    "EvalCase",
    "EvalExpectation",
    "EvalResponseMode",
    "OfflineEvalFixture",
    "OfflineEvidenceFixture",
    "load_eval_cases",
]
