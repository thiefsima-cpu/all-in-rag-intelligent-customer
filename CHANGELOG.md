# 更新日志

GraphRAG C9 的所有重要变更都记录在这里。

本项目遵循 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 格式，
并使用 `pyproject.toml` 中的包版本。

## 未发布

## 0.3.0rc1 - 2026-07-11

### 新增

- 将服务 API、构建 API、外部构建 worker、离线发布门禁、真实依赖门禁、实时质量门禁和本地压测工具统一维护在一个 Python 仓库中。
- 增加可配置的 answer failure copy，并贯穿服务装配、非流式响应和流式错误响应。
- 扩展企业质量语料、切片覆盖、LLM judge 和人工复核证据，记录真实依赖与实时质量门禁成功结果。
- 增加 API 压测场景分类、容量阈值、默认基线和机器可读报告。

### 变更

- 收紧应用、检索、图谱、生成和查询理解之间的端口与类型边界，并拆分 API 路由、组合服务和构建任务持久化热点。
- 将发布治理纳入 CI，覆盖 pytest、coverage、Ruff、mypy、离线发布门禁、依赖审计、密钥扫描和 SBOM 生成。
- 为公共 API 契约、质量语料资产和治理文件补齐 CODEOWNERS 保护。

### 修复

- 本地发布门禁在默认报告目录不可写时安全回退到临时目录。
- 压测报告未达到阈值时返回非零退出码，使自动化门禁能够可靠阻止发布。

### 安全

- 提升 `pip-audit` 识别出的易受攻击运行时和开发依赖 pin，包括 `langchain-core`、`langsmith`、`starlette`、`ujson` 和 `pip`。
- 增加安全策略、依赖审计、密钥扫描和 CycloneDX SBOM 发布证据。
