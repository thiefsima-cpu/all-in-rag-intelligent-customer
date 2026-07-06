"""Canonical runtime DTO contracts split by responsibility."""

from .analysis import (
    AnalysisInput,
    AnalysisMapping,
    QueryAnalysis,
    analysis_payload,
    analysis_strategy_name,
    analysis_value,
    ensure_optional_query_analysis,
    ensure_query_analysis,
)
from .errors import RuntimeErrorDetail
from .generation import GenerationMode, GenerationSnapshot
from .graph import GraphRetrievalSnapshot, GraphTraceEventSnapshot
from .policy import PolicySnapshot
from .retrieval import HybridRetrievalOutcome, RetrievalOutcome
from .routing import RouteDiagnostics, RouteSnapshot, RouteStageSnapshot
from .tracing import (
    AnswerTraceSnapshot,
    ModelSuiteSnapshot,
    QueryDiagnostics,
    QueryTraceEvent,
    RetrievalTraceSnapshot,
)
from .workflows import AnswerContext, QueryUnderstandingSnapshot, RouteResolution

__all__ = [
    "AnswerContext",
    "AnswerTraceSnapshot",
    "AnalysisInput",
    "AnalysisMapping",
    "GenerationMode",
    "GenerationSnapshot",
    "GraphRetrievalSnapshot",
    "GraphTraceEventSnapshot",
    "HybridRetrievalOutcome",
    "ModelSuiteSnapshot",
    "PolicySnapshot",
    "QueryAnalysis",
    "QueryDiagnostics",
    "QueryTraceEvent",
    "QueryUnderstandingSnapshot",
    "RetrievalOutcome",
    "RetrievalTraceSnapshot",
    "RouteDiagnostics",
    "RouteResolution",
    "RouteSnapshot",
    "RouteStageSnapshot",
    "RuntimeErrorDetail",
    "analysis_payload",
    "analysis_strategy_name",
    "analysis_value",
    "ensure_optional_query_analysis",
    "ensure_query_analysis",
]
