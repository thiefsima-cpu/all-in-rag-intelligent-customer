# Live Quality Gate

Status: FAIL

## Target

- api_host: `localhost:8000`
- judge_host: `dashscope.aliyuncs.com`

## Metrics

- case_count: `0`
- pass_rate: `0.0`
- deterministic_pass_rate: `0.0`
- judge_pass_rate: `None`
- recall_at_k: `None`
- mrr: `None`
- ndcg_at_k: `None`
- fallback_rate: `0.0`
- retrieval_degradation_rate: `0.0`
- p95_latency_ms: `0.0`
- estimated_cost_usd: `0`
- avg_judge_scores: `{}`

## Failing Checks

- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `live_quality_debug_answer_request`: `LIVE_QUALITY_REQUEST_FAILED`
- `metrics.case_count`: `METRIC_BELOW_MINIMUM`
- `metrics.pass_rate`: `METRIC_BELOW_MINIMUM`
- `metrics.deterministic_pass_rate`: `METRIC_BELOW_MINIMUM`
- `metrics.judge_pass_rate`: `METRIC_NOT_NUMERIC`
- `metrics.recall_at_k`: `METRIC_NOT_NUMERIC`
- `metrics.mrr`: `METRIC_NOT_NUMERIC`
- `metrics.ndcg_at_k`: `METRIC_NOT_NUMERIC`
- `coverage.risk_tags.prompt_injection`: `SLICE_COVERAGE_MISSING`
- `coverage.risk_tags.knowledge_pollution`: `SLICE_COVERAGE_MISSING`
- `coverage.risk_tags.no_evidence_inducement`: `SLICE_COVERAGE_MISSING`
- `coverage.risk_tags.cross_language`: `SLICE_COVERAGE_MISSING`
- `coverage.risk_tags.typo`: `SLICE_COVERAGE_MISSING`
- `coverage.risk_tags.long_query`: `SLICE_COVERAGE_MISSING`
- `coverage.risk_tags.constraint_heavy`: `SLICE_COVERAGE_MISSING`
- `coverage.query_types.single_recipe`: `SLICE_COVERAGE_MISSING`
- `coverage.query_types.recommendation`: `SLICE_COVERAGE_MISSING`
- `coverage.query_types.safety`: `SLICE_COVERAGE_MISSING`
- `coverage.query_types.multi_hop`: `SLICE_COVERAGE_MISSING`
- `coverage.query_types.constraint`: `SLICE_COVERAGE_MISSING`
- `coverage.cuisines.sichuan`: `SLICE_COVERAGE_MISSING`
- `coverage.cuisines.home_style`: `SLICE_COVERAGE_MISSING`
- `coverage.cuisines.general`: `SLICE_COVERAGE_MISSING`
- `coverage.constraint_types.evidence_grounding`: `SLICE_COVERAGE_MISSING`
- `coverage.constraint_types.time`: `SLICE_COVERAGE_MISSING`
- `coverage.constraint_types.diet`: `SLICE_COVERAGE_MISSING`
- `coverage.constraint_types.ingredient`: `SLICE_COVERAGE_MISSING`
- `coverage.response_modes.grounded_answer`: `SLICE_COVERAGE_MISSING`
- `coverage.response_modes.no_evidence`: `SLICE_COVERAGE_MISSING`
- `coverage.response_modes.clarification`: `SLICE_COVERAGE_MISSING`
- `slice.risk_tags.prompt_injection.case_count`: `METRIC_BELOW_MINIMUM`
- `slice.risk_tags.prompt_injection.pass_rate`: `METRIC_BELOW_MINIMUM`
- `slice.risk_tags.knowledge_pollution.case_count`: `METRIC_BELOW_MINIMUM`
- `slice.risk_tags.knowledge_pollution.pass_rate`: `METRIC_BELOW_MINIMUM`
- `slice.risk_tags.no_evidence_inducement.case_count`: `METRIC_BELOW_MINIMUM`
- `slice.risk_tags.no_evidence_inducement.pass_rate`: `METRIC_BELOW_MINIMUM`

## Manual Review

- sample_count: `0`
