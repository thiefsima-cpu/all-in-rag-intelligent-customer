from __future__ import annotations

from .models import CoverageEvaluation, CoveragePolicy, CoverageRuleResult
from .snapshot import CoverageSnapshot


def evaluate_policy(
    policy: CoveragePolicy,
    snapshot: CoverageSnapshot,
) -> CoverageEvaluation:
    package_counts = snapshot.package_counts(policy.package.path)
    if package_counts.num_branches == 0:
        raise ValueError(f"package has no branch data: {policy.package.path}")
    results = [
        CoverageRuleResult(
            kind="package",
            path=policy.package.path,
            counts=package_counts,
            branch_fail_under=policy.package.branch_fail_under,
        )
    ]
    for rule in policy.risk_modules:
        counts = snapshot.file_counts(rule.path)
        if counts.num_branches == 0:
            raise ValueError(f"configured risk file has no branch data: {rule.path}")
        results.append(
            CoverageRuleResult(
                kind="risk_module",
                path=rule.path,
                counts=counts,
                combined_fail_under=rule.combined_fail_under,
                branch_fail_under=rule.branch_fail_under,
            )
        )
    return CoverageEvaluation(results=tuple(results))
