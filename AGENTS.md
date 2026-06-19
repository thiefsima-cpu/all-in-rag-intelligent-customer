# AGENTS.md

## 项目概览

GraphRAG C9 将服务 API、构建 API、离线评估门禁和本地压测工具放在同一个
Python 仓库中。

- `rag_modules/` 是生产代码包。
- `rag_modules/interfaces/api/` 是 FastAPI 边界。
- `rag_modules/app/` 负责应用装配、组合、生命周期和服务编排。
- `rag_modules/retrieval/`、`rag_modules/graph/`、`rag_modules/generation/`
  和 `rag_modules/query_understanding/` 是主要 RAG 子系统。
- `profiles/` 存放运行时 profile 的 TOML 配置。
- `scripts/` 存放 smoke 检查、release gate、环境验证和运维辅助脚本。
- `tests/` 是行为契约。修改行为时，优先在这里添加或更新聚焦测试。
- `agent/` 是独立的菜谱知识图谱辅助工具，有自己的依赖和约定。除非任务明确
  针对它，否则不要把它的依赖或风格混入主包。

## 环境与初始化

- 使用 Python 3.11。`pyproject.toml` 要求 `>=3.11,<3.12`。
- Windows 下优先使用仓库自带脚本初始化开发环境：

  ```powershell
  .\scripts\bootstrap_env.ps1 -Profile dev
  ```

- `pyproject.toml` 是依赖来源的准绳。
- `requirements.txt` 和 `requirements-dev.txt` 是生成出来的锁定文件，供 Docker
  和初始化脚本使用。依赖变更时不要手改这两个文件；用 Python 3.11 重新生成：

  ```powershell
  python -m piptools compile pyproject.toml --output-file requirements.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple"
  python -m piptools compile pyproject.toml --extra dev --output-file requirements-dev.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple"
  ```

- 以 `.env.example` 作为本地 `.env` 的模板。不要提交真实 API key、数据库凭证、
  token 或客户数据。
- Docker API profile 的启动命令是：

  ```powershell
  docker compose --profile api up --build
  ```

  只有任务确实需要集成行为时，才启动 Docker 服务。

## 常用命令

- 运行完整测试：

  ```powershell
  python -m pytest -q
  ```

- 运行单个测试文件：

  ```powershell
  python -m pytest tests/test_api_app.py -q
  ```

- 运行仓库 hooks：

  ```powershell
  pre-commit run --all-files
  ```

  Ruff hook 可能会自动修改文件；运行后要检查 diff。

- 运行离线 release gate：

  ```powershell
  python scripts/release_gate.py
  ```

- 运行本地压测工具：

  ```powershell
  python scripts/pressure_api_service.py --json
  ```

- `pyproject.toml` 中定义的控制台入口：

  ```powershell
  graph-rag-api
  graph-rag-build-api
  graph-rag-release-gate
  graph-rag-pressure
  graph-rag-verify-env
  ```

## 编码约定

- 遵循现有模块边界。API 请求/响应相关逻辑放在
  `rag_modules/interfaces/api/`；运行时组合逻辑放在 `rag_modules/app/`；
  retrieval、graph、generation、query understanding 行为分别留在对应包内。
- 优先使用 profile 和配置驱动行为，避免硬编码环境值。
- 处理结构化数据时，优先使用已有的 Pydantic model 或 dataclass；不要在已有
  类型模式足够时临时堆 ad hoc 字典。
- 谨慎新增生产依赖。确实需要新增 runtime 依赖时，更新 `pyproject.toml`，重新
  生成两个 requirements 锁文件，并说明为什么它属于生产依赖而不是 `dev` extra。
- Ruff 目标是 Python 3.11、100 字符行宽、导入排序和双引号格式。完成代码修改前，
  运行 `pre-commit run --all-files` 或等价的 Ruff 命令。
- 聚焦修复时避免大范围重构。除非任务明确要求，否则不要破坏
  `tests/test_public_surface_boundaries.py` 和
  `tests/test_public_api_manifest.py` 覆盖的公共接口。

## 测试指导

- 修改行为时，即使用户只提到实现，也要添加或更新测试。
- 先运行最窄的相关测试；当改动触及共享 runtime、API、retrieval、graph、
  generation 或配置路径时，再扩大验证范围。
- API 改动重点检查 `tests/test_api_app.py`、`tests/test_entrypoints.py` 和应用
  装配相关测试。
- retrieval 或 routing 改动要运行对应的检索/router 测试；跨子系统行为变更时，
  再运行 smoke route 脚本。
- generation prompt 改动只有在变化是有意的情况下才更新 snapshot fixtures，并
  运行 generation prompt 测试或 smoke 脚本。
- 对发布敏感的改动，在声明完成前运行 `python scripts/release_gate.py`。

## 生成数据与产物

- 将 `storage/`、`volumes/`、`.pytest_cache/`、`__pycache__/` 和
  `eval/reports/` 视为生成物或本地状态。除非任务明确要求，不要提交这些位置的
  新文件。
- `tests/fixtures/` 中的 fixture 变更必须可复现、易审阅。
- `cypher/` 中受版本控制的 Cypher 和 CSV 资产应保持小而明确。

## 文档与计划

- 修改公共工作流、初始化命令、release gate、API 行为或运维预期时，同步更新
  `README.md` 或 `docs/`。
- 现有设计和实现记录位于 `docs/superpowers/`。扩展相关子系统时，沿用其中的术语。

## Git 与交付预期

- 编辑前检查当前 diff，不要覆盖与任务无关的用户改动。
- 提交应聚焦当前任务。
- 最终交付时说明运行过哪些检查；如果有检查跳过或无法运行，也要明确写出。
