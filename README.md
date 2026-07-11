# GraphRAG C9

本仓库把服务 API、构建 API、离线门禁和本地压测工具放在同一个项目中，方便
GraphRAG C9 的开发、验证和交付。

## 环境初始化

安装 Miniconda 或 Anaconda，并确认 PowerShell 中可以使用 `conda`。Windows 下优先使用仓库自带的
bootstrap 脚本：

```powershell
.\scripts\bootstrap_env.ps1 -Profile dev
```

脚本会创建或复用全局 conda 环境 `graphrag-c9-dev`。运行本地工程命令前先激活它：

```powershell
conda activate graphrag-c9-dev
```

在已激活的开发环境中安装一次仓库 Git hook：

```powershell
python -m pre_commit install
```

运行服务前，把提交到仓库的环境模板复制为本地私有 `.env` 文件：

```powershell
Copy-Item .env.example .env
```

真实 API key、token 和客户专属配置只放在 `.env` 中。已提交的 `.env.example` 只用于说明必需变量，
里面只能保留占位符或安全默认值。

`pyproject.toml` 是依赖来源的准绳。运行时直接依赖放在 `[project.dependencies]` 中；开发工具放在
`dev` optional dependency group 中。`requirements.txt` 和 `requirements-dev.txt` 是生成出来的锁定文件，
供 Docker 和 bootstrap 脚本使用。

使用 Python 3.11 重新生成两个锁文件：

```powershell
.\scripts\compile_locks.ps1
```

## 工程入口

以 editable 模式安装仓库后，可以使用 `pyproject.toml` 中定义的控制台命令：

```powershell
graph-rag-api
graph-rag-build-api
graph-rag-release-gate
graph-rag-integration-gate
graph-rag-live-quality-gate
graph-rag-local-gate
graph-rag-pressure
graph-rag-verify-env
```

## 架构说明

运行时装配、从 query 到 answer 的流程，以及构建工作流状态机，请先阅读
[docs/architecture.md](docs/architecture.md)。如果只想快速跟完一次 `/v1/answers` 请求，先看其中的
“请求生命周期最短阅读路线”。

## 版本治理

GraphRAG C9 同时跟踪三个版本轴：

- 包版本：`0.3.0rc1`，来源于 `pyproject.toml` 的 `[project].version`。它是 Python 分发包和发布版本，
  用于包发布、发布说明和客户升级指引。
- API 版本：`1.0.0`，来源于 `API_VERSION`，API 前缀是 `/v1`。它是服务 API 和构建 API 共享的
  HTTP/OpenAPI 契约版本。
- 兼容性移除版本：`0.2.0`，来源于 `LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION`，并由
  [docs/public_surface_retirement_plan.md](docs/public_surface_retirement_plan.md) 中的行级里程碑补充说明。
  这些信息记录兼容性表面首次被移除的包版本或 API 版本。

包发布可以保持相同 API 版本；API 契约变化也不意味着包版本必须同步变化。兼容性移除在进入发布说明或客户迁移指引前，
必须明确版本轴，例如包版本 `0.3.0` 或 API 版本 `1.0.0`。

## 常用命令

```powershell
python scripts/local_gate.py
python -m pytest -q
python -m pre_commit run --all-files
python scripts/check_encoding.py
graph-rag-release-gate
graph-rag-integration-gate --json
graph-rag-live-quality-gate --json
python scripts/pressure_api_service.py --json
```

发布前的最终本地门禁优先使用 `python scripts/local_gate.py`。它会按顺序串联
`pre-commit run --all-files`、`python scripts/check_encoding.py`、`python -m pytest -q` 和
`python scripts/release_gate.py`，并在第一个失败点停止。

API capacity formulas and pressure threshold interpretation are documented in
[docs/api_capacity_and_pressure_thresholds.md](docs/api_capacity_and_pressure_thresholds.md).

质量门禁分为三层，彼此独立：

- `graph-rag-release-gate`：确定性的契约回归检查，不依赖外部服务。
- `graph-rag-integration-gate`：验证 Neo4j、Milvus、服务 API 和模型提供方等真实依赖是否参与。
- `graph-rag-live-quality-gate`：使用真实检索、真实生成、确定性排序指标、LLM judge 评分、
  人工复核样本和切片指标证明线上质量。

实时门禁只在已准备好的环境中显式运行。它们不会进入默认 pytest、pre-commit、`scripts/local_gate.py`
或离线发布门禁。前置条件、成本控制、报告和 CI 调度请见
[docs/real_dependency_integration_gate.md](docs/real_dependency_integration_gate.md) 和
[docs/live_quality_gate.md](docs/live_quality_gate.md)。

## 企业治理

组织级约束由 GitHub 承载：

- [CI](.github/workflows/ci.yml) 运行 Ruff、mypy、带 coverage 的 pytest、离线发布门禁、`pip-audit`、
  secret scanning 和 SBOM 生成。
- [CODEOWNERS](.github/CODEOWNERS) 为公共 API 契约、质量语料资产和治理文件分配必要 reviewer；
  启用 branch protection 的 code-owner review 后会强制生效。
- [SECURITY.md](SECURITY.md) 说明漏洞报告流程和必需安全门禁。
- [CHANGELOG.md](CHANGELOG.md) 使用 `pyproject.toml` 中的包版本记录发布说明。
- [docs/release_process.md](docs/release_process.md) 定义发布 checklist、必需 GitHub checks、coverage 策略、
  SBOM 留存和版本 bump 流程。

## Docker

根目录的 `docker-compose.yml` 将基础设施和 API 表面分开。启动 API profile：

```powershell
docker compose --profile api up --build
```

API profile 会启动两个应用表面：

- 服务 API：<http://localhost:8000/docs>
- 构建 API：<http://localhost:8001/docs>

API 容器由 `Dockerfile.api` 构建，并加入同一个 compose 文件中声明的 Milvus 和 Neo4j 服务。启动 API profile
前，在项目 `.env` 文件中配置 `DASHSCOPE_API_KEY`；Compose 会把该值转发给 API 容器。`OPENAI_API_KEY` 和
`MOONSHOT_API_KEY` 也会作为备用模型提供方 key 转发。服务 API 会在启动时验证这个轻量模型提供方要求，
因此缺少 key 时会快速失败并给出清晰错误，而不是等到第一次 `/v1/answers` 请求才暴露问题。

默认 `AUTO_BOOTSTRAP=true` 时，同一个 Compose 命令还会运行一次性 bootstrap 服务。全新状态下，它会导入 CSV
图谱并构建知识库产物；后续启动时，如果 recipe 数据已经存在，它会跳过图谱导入，并让构建工作流复用有效产物。
bootstrap 成功后服务 API 才会启动，并自动初始化检索运行时。

查看启动进度：

```powershell
docker compose logs bootstrap
```

在 `.env` 中设置 `FORCE_REBUILD=true`，可在下一次 bootstrap 期间提交 `/jobs/rebuild`。设置
`AUTO_BOOTSTRAP=false` 可用于生产式部署，此时图谱导入和构建任务由外部流程管理。构建 API 仍可用于显式操作：

```powershell
$job = Invoke-RestMethod -Method Post http://localhost:8001/v1/jobs/build
Invoke-RestMethod http://localhost:8001/v1/jobs/$($job.job.job_id)
```

### 构建任务控制与历史

构建 API 的 `/v1/jobs/build` 和 `/v1/jobs/rebuild` 提交路由接受 `Idempotency-Key`。同一个 key 用于同一种操作时，
会返回原始 job；同一个 key 用于不同操作时，会返回 `409 BUILD_JOB_CONFLICT`。

排队中或运行中的 job 可以协作式取消：

```powershell
Invoke-RestMethod -Method Post `
  "http://localhost:8001/v1/jobs/$($job.job.job_id)/cancel"
```

运行中的 job 会先进入 `cancel_requested`，当构建工作流抵达下一个进度 checkpoint 后变为 `cancelled`。
失败或取消的 job 可通过 `POST /v1/jobs/{job_id}/retry` 重试。重试会创建新 job，并在 `retry_of_job_id`
中记录原始标识；原始历史不会被改写。

`GET /v1/jobs` 返回有上限的分页结果：

```powershell
curl.exe -H "Authorization: Bearer $env:API_ACCESS_TOKEN" `
  "http://localhost:8001/v1/jobs?limit=50"
```

沿着 `next_cursor` 读取，直到它为空。构建任务历史按照 `API_BUILD_JOB_RETENTION_LIMIT` 保留；活跃 job
永远不会被裁剪。如果本地 job storage 中存在损坏记录，`/v1/diagnostics` 会报告安全的
`build_job_store.warning_count` 和稳定 warning code，不会暴露原始文件内容。

默认执行后端由 `API_BUILD_JOB_RUNNER_BACKEND` 配置。本地开发默认是 `in_process`；生产部署可切换为
`external_worker`，此时 Build API 只持久化 queued job，独立的 `graph-rag-build-worker` 进程轮询、认领
并执行任务。executor 并发由 `API_BUILD_JOB_RUNNER_MAX_WORKERS` 控制，默认值为 `1`；worker 空闲轮询间隔由
`API_BUILD_JOB_WORKER_POLL_INTERVAL_SECONDS` 控制，默认值为 `1`。已接受的排队 job 会先持久化再分发，并在
worker 启动或重启时重新认领。已认领 job 由 lease 保护，`API_BUILD_JOB_LEASE_SECONDS` 默认 `30`；worker
heartbeat 由 `API_BUILD_JOB_HEARTBEAT_SECONDS` 控制，默认 `10`。如果进程在持有 job 时停止，下一次启动会让
lease 过期，并将 job 报告为安全的 failed/interrupted build，而不是让它永久处于 running。

构建任务存储会从旧 V2 文件一次性迁移为配置的 `BUILD_JOB_STORE_PATH` 目录下的 V3 event envelope，并保留原始
V2 目录为 `build_jobs.v2.backup`。当前 release 包含 `in_process` 和 `external_worker` 两个 runner backend；
未来的 repository backend 仍必须实现构建任务 repository port，并在 composition 中选择。

在构建 API 生成 ready artifact manifest、cached documents 和 Milvus vector collection 前，`/v1/answers`
会返回 `409 Conflict`。

### 错误契约与请求关联

所有 HTTP 失败都使用
`{"ok": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}`。错误码稳定；错误消息可安全展示，
且不会包含原始异常。Validation details 只包含字段路径和原因，不包含被拒绝的输入。

客户端可以提供 `X-Request-ID`，允许 1 到 128 个 ASCII 字母、数字、`.`、`_`、`:` 或 `-`。如果 header
缺失或无效，服务会生成替代值。解析后的 ID 会出现在每个响应的 `X-Request-ID` header 中，也会出现在每个错误体中。
SSE 错误事件使用相同 payload。

应用日志不会记录原始问题、query tokens、prompts、凭证或异常消息。支持排障时，请通过 `request_id` 和稳定错误码关联活动。

失败的构建任务资源包含 typed `error` 对象，其中有稳定 code、由 catalog 控制的消息，以及提交请求 ID。

### 版本化 API 与调试追踪

新 API client 应使用 `/v1`。未版本化的服务和构建路由已经退役；调用方应改用匹配的 `/v1` 路径。

公开答案路由 `/v1/answers` 和 `/v1/answers/stream` 暴露字段级公共契约：

- `summary`：最终答案、状态、策略、延迟、证据数量、fallback、token 和成本汇总字段。
- `grounding.evidence_documents`：只包含公共 citation 字段，即 `content`、`recipe_name`、`score`、`source`、
  `evidence_type` 和 `matched_terms`。
- `diagnostics`：稳定的健康度和降级字段，例如 `overall_bucket`、`retrieval_degraded`、`degraded_sources`
  和安全的 degraded-candidate code。

公共响应不会暴露路由解析、答案上下文、检索结果、查询计划、语义画像、图证据映射、证据单元、元数据包或
trace 快照。完整运行时细节只通过显式 debug 路由提供：

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/v1/debug/answers -Body (@{question="..."} | ConvertTo-Json) -ContentType application/json
```
