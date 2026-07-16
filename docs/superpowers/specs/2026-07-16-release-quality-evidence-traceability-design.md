# Release Quality Evidence Traceability Design

## Context

The repository contains a human-authored success record for the 2026-07-10 live gates. It states
that the live quality gate passed 34/34 cases with Recall@K 1.0, MRR 0.913043, and nDCG@K
0.935814. The only version-controlled live-quality machine report, however, is an earlier failed
run under `quality-evidence/live_quality_gate/20260708-203513/` with `case_count=0`.

The failed report is valid evidence of a failed attempt. It is not evidence that current quality is
failing. The audit gap is that the successful conclusion is not bound to a version-controlled
machine manifest that identifies the evaluated commit, runtime profile, model suite, evaluation
dataset, knowledge-base artifact, and full report digests.

The live quality gate currently writes replaceable local output under
`eval/reports/live_quality_gate/`. The tag-triggered release workflow retains distributions and an
SBOM, but it does not verify or retain live quality evidence. Release reviewers therefore cannot
start from a release version and deterministically locate the exact machine reports supporting its
quality conclusion.

## Goals

- Give every release one machine-readable, version-controlled quality-evidence manifest.
- Bind the successful live quality run to the exact evaluated Git commit.
- Record the runtime profile, serving and judge models, evaluation dataset, and knowledge-base
  artifact summary without exposing credentials or host-local paths.
- Keep the compact manifest in Git while keeping complete reports in release assets.
- Make release automation reject zero-case, failed, stale, incomplete, missing, expired, or
  tampered evidence.
- Preserve failed attempts as diagnostic history without allowing them to be discovered as release
  success evidence.
- Reuse the existing live quality, integration, diagnostics, and artifact-manifest contracts rather
  than adding a new production API.

## Non-goals

- Do not commit complete live gate reports, answer previews, evidence snippets, or manual-review
  JSONL files for every release.
- Do not make live quality execution part of default pytest, pre-commit, `scripts/local_gate.py`, or
  the deterministic offline release gate.
- Do not start, stop, rebuild, or mutate the target Neo4j, Milvus, serving, or model-provider
  infrastructure.
- Do not add a general-purpose provenance database, signing service, transparency log, or external
  artifact store.
- Do not retroactively claim that the tracked 2026-07-08 failed report supports the 2026-07-10
  success conclusion.
- Do not store credentials, authorization headers, raw provider responses, raw exceptions,
  customer data, or credential-bearing URLs.

## Considered Approaches

### Extend the live quality gate directly

The live quality gate could collect Git, profile, diagnostics, release, and artifact transport
metadata itself. This has the smallest number of commands, but it couples quality evaluation to
release governance and GitHub artifact handling. It also makes local diagnostic executions carry
release-only responsibilities.

### Add an independent release-evidence packager

An independent package can consume the existing gate reports, policies, a safe diagnostics
snapshot, Git metadata, and CI artifact metadata. It can validate the cross-file relationship,
produce a compact manifest, and verify the same manifest during tag publication.

This is the chosen approach. It keeps gate ownership intact, provides a testable local contract,
and allows release transport to change without changing quality scoring.

### Assemble the evidence only in workflow YAML

The workflows could use shell and YAML expressions to calculate hashes and construct JSON. This
would avoid a Python package, but it would be difficult to test locally, duplicate validation
logic, and make strict schema and security projection regressions more likely.

## Chosen Architecture

Add a separate `scripts/release_evidence/` application with three operations:

- `capture`: validate source reports and runtime diagnostics, build a complete evidence bundle, and
  write a capture receipt containing stable hashes and summaries;
- `finalize`: combine the capture receipt with immutable GitHub Actions artifact metadata and write
  the compact manifest that is committed to Git;
- `verify`: validate a committed manifest, its Git relationship, downloaded artifact metadata, and
  every file in the complete evidence bundle.

The live quality gate and integration gate remain independent applications. The release-evidence
application consumes their outputs but does not change their pass/fail semantics.

Runtime identity has two sources:

- model names come from the existing model-suite diagnostics;
- safe target identity comes from the already-sanitized gate settings and diagnostics;
- the profile name and hash plus the knowledge-base signatures and counts come from the active
  artifact manifest JSON supplied to the evidence job.

The current public diagnostics response intentionally omits graph, document, embedding, and index
signatures. The evidence workflow therefore reads a target-environment export of the active
artifact manifest rather than assuming those fields exist in `/v1/diagnostics`. The input may be a
mounted manifest file on a secured runner or an artifact exported by the environment-preparation
job. The release-evidence application projects it to safe fields before retention.

No new production endpoint is required.

## Storage Layout

The compact, version-controlled manifest lives at:

```text
quality-evidence/
  README.md
  releases/
    <package-version>/
      evidence-manifest.json
```

For example:

```text
quality-evidence/releases/0.4.0rc1/evidence-manifest.json
```

Only manifests below `quality-evidence/releases/` are discoverable as release success evidence.
The current `quality-evidence/live_quality_gate/20260708-203513/` directory remains a historical
failed attempt and is explicitly described as such in `quality-evidence/README.md`.

Generated local intermediates remain ignored:

```text
eval/reports/release_evidence/<package-version>/
  capture-receipt.json
  graph-rag-c9-<package-version>-quality-evidence.zip
```

The complete ZIP is uploaded first as a pre-release workflow artifact. The finalized manifest is
uploaded as a second small workflow artifact so a maintainer can add it to the governed release
pull request.

## Complete Evidence Bundle

The release evidence ZIP contains only allowlisted files:

```text
integration_gate/report.json
integration_gate/summary.md
live_quality_gate/report.json
live_quality_gate/summary.md
live_quality_gate/manual_review_sample.jsonl
runtime/diagnostics.json
runtime/artifact_manifest.json
policies/integration_gate.json
policies/live_quality_gate.json
capture-receipt.json
checksums.json
```

The runtime diagnostics and artifact-manifest files are security projections, not raw source
payloads. They contain only the fields used by the manifest. Profile paths are retained only when
they normalize to a repository-relative `profiles/` path; absolute or external paths are omitted.

The ZIP is created deterministically from sorted paths with normalized timestamps and permissions.
Its SHA-256 and byte count are recorded in the capture receipt and final manifest. Individual file
SHA-256 values and byte counts are recorded separately in `checksums.json`.

## Compact Manifest Contract

The strict schema identifier is `graph-rag-release-evidence-v1`. Unknown fields are rejected. A
representative manifest is:

```json
{
  "schema_version": "graph-rag-release-evidence-v1",
  "release": {
    "package_version": "0.4.0rc1",
    "tag": "v0.4.0-rc.1"
  },
  "provenance": {
    "repository": "owner/repository",
    "evaluated_commit": "0123456789abcdef0123456789abcdef01234567",
    "generated_at": "2026-07-16T08:00:00+00:00"
  },
  "integration": {
    "passed": true,
    "report_schema_version": 1,
    "generated_at": "2026-07-16T07:55:00+00:00",
    "metrics": {
      "check_count": 30,
      "failed_count": 0,
      "case_count": 3,
      "executed_case_count": 3,
      "observation_count": 3
    }
  },
  "quality": {
    "passed": true,
    "report_schema_version": 1,
    "generated_at": "2026-07-16T07:50:00+00:00",
    "metrics": {
      "case_count": 34,
      "pass_rate": 1.0,
      "deterministic_pass_rate": 1.0,
      "judge_pass_rate": 1.0,
      "recall_at_k": 1.0,
      "mrr": 0.913043,
      "ndcg_at_k": 0.935814,
      "fallback_rate": 0.0,
      "retrieval_degradation_rate": 0.0,
      "p95_latency_ms": 21413.888,
      "estimated_cost_usd": 0.04119053
    },
    "manual_review_sample_count": 34
  },
  "runtime": {
    "target": {
      "api_host": "quality.example.com",
      "judge_host": "judge.example.com"
    },
    "profile": {
      "name": "eval_quality",
      "path": "profiles/eval_quality.toml",
      "resolved_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    },
    "models": {
      "llm": "qwen3.7-plus",
      "embedding": "qwen3-vl-embedding",
      "rerank": "qwen3-vl-rerank",
      "judge": "qwen3.7-plus"
    }
  },
  "dataset": {
    "path": "eval/live_quality_gate.json",
    "schema_version": 1,
    "case_count": 34,
    "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "knowledge_base": {
    "schema_version": "graph-rag-artifact-manifest-v2",
    "manifest_version": 7,
    "stage": "ready",
    "health": "ready",
    "published_at": "2026-07-16T07:30:00+00:00",
    "index_version": "v000007",
    "collection_name": "cooking_knowledge__active",
    "graph_signature": "graph-signature",
    "document_signature": "document-signature",
    "embedding_signature": "embedding-signature",
    "index_signature": "index-signature",
    "total_documents": 323,
    "total_chunks": 1543,
    "vector_rows": 1543
  },
  "bundle": {
    "name": "graph-rag-c9-0.4.0rc1-quality-evidence.zip",
    "bytes": 123456,
    "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  },
  "artifacts": [
    {
      "name": "live_quality_report",
      "path": "live_quality_gate/report.json",
      "bytes": 12345,
      "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    }
  ],
  "transport": {
    "provider": "github-actions",
    "workflow_run_id": 123456789,
    "workflow_head_sha": "0123456789abcdef0123456789abcdef01234567",
    "artifact_id": 987654321,
    "artifact_name": "graph-rag-c9-0.4.0rc1-quality-evidence",
    "artifact_digest": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
  }
}
```

The production schema contains an artifact entry for every file in the complete bundle. Digests
must be lowercase SHA-256 values. Commit IDs must be full 40-character hexadecimal SHA-1 IDs used
by the current repository. Metrics reject booleans, strings, NaN, and infinity.

## Capture Validation

`capture` accepts only a clean checkout at the supplied `evaluated_commit`. It validates:

- the package version and planned tag follow the repository's existing version/tag mapping;
- the integration report has `passed=true`, nonzero checks, and all live cases executed;
- the live quality report has `passed=true`;
- live quality `case_count` is greater than zero and meets the policy minimum;
- pass, deterministic, and judge rates are finite numeric values;
- Recall@K, MRR, and nDCG@K are finite numeric values;
- fallback, degradation, latency, and cost are finite numeric values;
- report artifacts named inside each report exist;
- the policy case count equals the report case count;
- the live policy hash matches the file at `evaluated_commit`;
- the artifact manifest's profile hash matches the resolved base-plus-selected-profile hash
  recomputed at `evaluated_commit`;
- model names are nonblank stable labels;
- the artifact manifest has `stage=ready` and `health=ready`;
- graph, document, embedding, and index signatures are nonblank;
- document, chunk, and vector counts are positive;
- every complete-bundle input stays below its configured maximum size;
- all projected and rendered outputs pass the sensitive-data scanner.

The scanner rejects sensitive key names and values including API keys, bearer tokens,
authorization headers, passwords, raw exceptions, query-bearing URLs, and host-local absolute
paths. It is a final defense after allowlist projection, not a substitute for projection.

Failed runs may retain their original gate artifacts for diagnosis, but `capture` does not create a
successful capture receipt or finalizable manifest for them.

## Two-Phase Workflow Artifact Handoff

The pre-release evidence workflow runs on a runner that can reach the prepared target environment.
Runner placement is an operational concern: a hosted runner may be used for a reachable
pre-release environment, while a private local environment requires an appropriately secured
self-hosted runner.

The workflow:

1. Checks out the requested candidate commit with full history.
2. Verifies the checkout is clean and records the full commit ID.
3. Installs the Python 3.11 development environment from the locked requirements.
4. Runs the real-dependency integration gate.
5. Runs the live quality gate with the judge enabled.
6. Reads the serving diagnostics endpoint and writes the safe runtime projection.
7. Reads the active artifact manifest supplied by the target-environment preparation step and
   writes its safe projection.
8. Runs `release-evidence capture`.
9. Uploads the complete evidence ZIP as a workflow artifact.
10. Uses the upload result's artifact ID and digest plus the workflow run ID and head SHA to run
   `release-evidence finalize`.
11. Uploads the finalized compact manifest as a separate artifact.

The two-phase process avoids a circular dependency: the final manifest can reference the immutable
workflow artifact identity, while the complete artifact does not need to contain the final
manifest.

The finalized manifest is reviewed and committed to the release pull request. Attempt artifacts
remain outside Git. Only the selected successful manifest enters
`quality-evidence/releases/<package-version>/`.

## Git Provenance and Self-reference

A file cannot reliably contain the commit ID of the commit that contains that file. The manifest
therefore records `evaluated_commit`, the exact candidate commit on which both live gates ran.

The evidence manifest is added in a later commit. The release verifier requires:

- `evaluated_commit` exists and is an ancestor of the tag commit;
- the source branch was evaluated after version and changelog preparation;
- the tree difference from `evaluated_commit` to the tag commit contains only
  `quality-evidence/releases/<package-version>/evidence-manifest.json`;
- the manifest's package version matches `pyproject.toml`;
- the manifest's planned tag matches the actual tag;
- the workflow artifact metadata reports the same head SHA as `evaluated_commit`.

The governed pull-request flow may add a merge commit. Because the source branch must be current
with its target before merge, the merge result must have the same release tree plus the evidence
manifest. Any additional code, configuration, policy, profile, prompt, dependency, or knowledge
asset change invalidates the evidence and requires a new live run.

## Release Verification and Publication

The tag-triggered release workflow gains an evidence-verification phase before distributions are
published as release assets:

1. Resolve the package version and expected tag using the existing provenance rules.
2. Locate exactly one manifest for that version.
3. Run local schema, Git, and version verification.
4. Query the GitHub Actions artifact by the recorded artifact ID.
5. Require that the artifact is unexpired and its name, digest, run ID, and head SHA match the
   manifest.
6. Download the complete evidence ZIP.
7. Verify the ZIP byte count, ZIP SHA-256, allowed members, member sizes, and member SHA-256 values.
8. Recompute the report, policy, dataset, runtime, profile, and knowledge-base summaries and compare
   them with the compact manifest.
9. Build the wheel, sdist, and SBOM only after quality evidence verification passes.
10. Create or update a draft GitHub Release for the existing tag and upload the wheel, sdist, SBOM,
    compact evidence manifest, and complete evidence ZIP.
11. Keep the existing Actions release artifact for CI review as an additional copy.

RC tags create a draft prerelease. Final tags create a draft normal release. A maintainer reviews
the generated assets and release notes before publishing the draft.

The workflow uses repository-scoped GitHub credentials and changes release permissions from
read-only to the minimum contents permission required to create a draft and upload assets. It does
not expose target-environment credentials to the tag workflow; those credentials exist only in the
pre-release evidence workflow.

## Failure and Retry Semantics

- Integration or live quality failure: preserve diagnostic workflow artifacts, but do not produce a
  finalizable success manifest.
- Invalid diagnostics or security projection: fail capture and do not upload a successful bundle.
- Missing or mismatched upload metadata: fail finalization.
- Missing, expired, renamed, overwritten, or digest-mismatched workflow artifact: block release
  before tag creation through the pre-tag verifier.
- Code or configuration changes after `evaluated_commit`: invalidate the evidence and require a new
  run.
- Tag workflow bundle mismatch: fail before creating or updating the draft Release.
- Same package version with multiple manifests at the tagged tree: fail as ambiguous evidence.
- Before tagging, a superseded successful run may be replaced only by committing a newly finalized
  manifest and rerunning all pre-tag verification. The tagged tree freezes the selected manifest.
- After tagging, the release manifest is immutable. Corrections require a new release version or a
  separately identified erratum; the existing tag and evidence are not rewritten.

The release checklist requires the pre-tag artifact-existence check to pass immediately before tag
creation. The complete evidence artifact uses the maximum repository-supported retention window so
the tag workflow can promote it to a durable Release asset without relying on long-term Actions
artifact retention.

## Security and Privacy

The compact manifest is safe for Git and the complete evidence bundle is safe for repository
reviewers, but the two have different detail levels.

The compact manifest contains:

- safe host identities;
- stable model and profile labels;
- repository-relative paths;
- aggregate metrics;
- artifact counts, signatures, and digests;
- Git and workflow provenance.

The complete bundle may contain the existing answer previews, evidence snippets, and evaluation
queries already emitted by the live quality reporter. It remains access-controlled as a workflow
artifact and GitHub Release asset rather than being committed to Git.

Neither output may contain:

- environment values not on an allowlist;
- API keys or API tokens;
- Authorization headers;
- provider request or response headers;
- raw provider request or response bodies;
- raw exceptions or stack traces;
- customer data;
- credential-bearing URLs;
- absolute workstation paths.

## Component Boundaries

Create:

- `scripts/release_evidence/__init__.py` for the supported package exports;
- `scripts/release_evidence/__main__.py` for module execution;
- `scripts/release_evidence/models.py` for strict manifest, capture, artifact, runtime, and
  knowledge-base models;
- `scripts/release_evidence/capture.py` for source validation, allowlist projection, hashing, and
  deterministic bundle construction;
- `scripts/release_evidence/finalize.py` for workflow artifact metadata binding;
- `scripts/release_evidence/verifier.py` for manifest, Git, artifact, and bundle verification;
- `scripts/release_evidence/cli.py` for `capture`, `finalize`, and `verify`;
- `.github/workflows/release-evidence.yml` for the pre-release evidence run;
- `quality-evidence/README.md` for discovery and historical-failure semantics.

Modify:

- `.github/workflows/release.yml` to verify, retrieve, and publish evidence;
- `pyproject.toml` to add a `graph-rag-release-evidence` console entry without adding a dependency;
- `docs/live_quality_gate.md` to document capture and evidence retention;
- `docs/release_process.md` to make evidence verification and draft Release assets mandatory;
- relevant tests under `tests/`.

The package may import the existing gate report models and standard-library helpers. It must not
import private application composition internals or add a runtime dependency.

## Test Strategy

Implementation follows test-driven development.

### Manifest and capture tests

- A passing nonzero integration report and live quality report produce a strict capture receipt.
- A successful 34-case fixture preserves Recall@K, MRR, and nDCG values exactly.
- `case_count=0` is rejected even if a report incorrectly says `passed=true`.
- Failed gate status, missing judge metrics, non-finite metrics, blank models, missing profile hash,
  non-ready knowledge artifacts, blank signatures, or nonpositive artifact counts are rejected.
- Policy case count and report case count must agree.
- The active artifact manifest input is required and supplies the profile and knowledge-base
  signatures omitted from public diagnostics.
- Policy, profile, report, member, and bundle hashes are reproducible.
- ZIP member order, timestamps, permissions, and resulting SHA-256 are deterministic.
- Unknown fields and coerced scalar values are rejected.
- Sensitive keys, values, URLs, and absolute paths are rejected.

### Finalization tests

- Valid workflow run, head SHA, artifact ID, name, and digest produce a final manifest.
- Workflow head SHA must equal `evaluated_commit`.
- Missing, malformed, or mismatched transport metadata is rejected.
- Finalization cannot change capture-derived metrics, hashes, runtime identity, or artifact
  summaries.

### Verifier tests

- A temporary Git repository proves the evaluated-commit ancestor rule.
- An evidence-only commit after the evaluated commit passes.
- Any source, profile, policy, prompt, dependency, or workflow change after the evaluated commit
  fails.
- Package version and tag mismatches fail.
- Missing, duplicate, or wrong-version manifests fail.
- Missing, expired, renamed, or digest-mismatched Actions artifact metadata fails.
- Modified ZIP bytes, added ZIP members, path traversal members, oversized members, and modified
  report contents fail.
- Recomputed report, dataset, profile, and knowledge summaries must equal the manifest.

### Workflow and documentation tests

- The pre-release workflow runs both live gates before capture.
- The complete artifact upload precedes manifest finalization.
- The release workflow verifies evidence before building or publishing release assets.
- The release workflow uploads the compact manifest and complete ZIP to a draft Release.
- `quality-evidence/README.md` identifies only `releases/` as release success evidence.
- The historical `case_count=0` report is not selected by release evidence discovery.

### Verification commands

Run the narrow release-evidence tests first, then:

```powershell
python -m pytest tests/test_release_evidence_*.py tests/test_release_tag_policy.py -q
python -m pytest -q
pre-commit run --all-files
python scripts/release_gate.py
git diff --check
```

Because the change modifies a release-sensitive workflow, the offline release gate is mandatory
before completion. A real external evidence workflow is required to prove the operational path,
but unit tests use temporary repositories and fixture reports without model calls.

## Documentation and Operational Flow

The release checklist becomes:

1. Prepare the package version, changelog, and release configuration.
2. Push the candidate commit and run the pre-release evidence workflow against that exact commit.
3. Review the successful complete evidence artifact and finalized compact manifest.
4. Commit only the compact manifest to the release pull request.
5. Require local and CI checks, including pre-tag evidence verification, to pass.
6. Merge through the governed branch flow.
7. Create the protected tag only while the referenced evidence artifact is present and verified.
8. Let the tag workflow create the draft Release with distributions, SBOM, compact manifest, and
   complete evidence ZIP.
9. Review and publish the draft Release.

The human success narrative may still summarize results and operational lessons. It must link to
the release version and manifest rather than serving as the sole source of machine-verifiable
quality claims.

## Acceptance Criteria

- Every new RC or final release has exactly one
  `quality-evidence/releases/<package-version>/evidence-manifest.json`.
- The manifest identifies the evaluated commit, profile, serving models, judge model, live dataset,
  knowledge-base artifact, aggregate live metrics, complete artifact files, and transport identity.
- A zero-case or failed live quality report cannot produce a release-success manifest.
- The manifest and full evidence ZIP contain no forbidden sensitive data.
- The tag commit differs from the evaluated commit only by the selected compact manifest.
- The tag workflow retrieves the exact pre-release artifact and verifies all hashes before release
  publication.
- The draft GitHub Release contains distributions, SBOM, compact manifest, and complete quality
  evidence ZIP.
- The historical 2026-07-08 failed report remains available but is not discoverable as release
  success evidence.
- Focused tests, full pytest, pre-commit, the offline release gate, and `git diff --check` pass.
