# 更新日志

GraphRAG C9 的所有重要变更都记录在这里。

本项目遵循 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 格式，
并使用 `pyproject.toml` 中的包版本。

## 未发布

### 新增

- 企业治理 CI，覆盖 pytest、coverage、Ruff、mypy、离线发布门禁、依赖审计、密钥扫描和 SBOM 生成。
- 为公共 API 契约、质量语料资产和治理文件补齐 CODEOWNERS 保护。
- 安全策略和发布流程文档。

### 安全

- 提升 `pip-audit` 识别出的易受攻击运行时和开发依赖 pin，包括 `langchain-core`、`langsmith`、
  `starlette`、`ujson` 和 `pip`。

## 0.3.0 - 2026-07-05

### 新增

- 服务 API、构建 API、离线发布门禁、集成门禁、实时质量门禁和本地压测工具统一维护在一个 Python 仓库中。
