# 真实依赖门禁与实时质量门禁成功报告

## 结论

**PASS。** 最终镜像上的真实依赖门禁、实时质量门禁、人工复核、完整测试和离线发布门禁均通过。

- 执行日期：2026-07-10（Asia/Shanghai）
- 实时质量报告生成时间：2026-07-10 15:14:19 UTC
- 真实依赖报告生成时间：2026-07-10 15:16:06 UTC
- 目标：本机真实 Docker Compose API、Neo4j、Milvus 和 DashScope
- 生成模型：`qwen3.7-plus`，显式关闭 thinking
- 向量模型：`qwen3-vl-embedding`，维度 1024
- 重排模型：`qwen3-vl-rerank`
- Judge：`qwen3.7-plus` 独立调用，JSON-object 输出，显式关闭 thinking

报告和门禁产物不包含 API key、Authorization header 或带凭据 URL。

## 两道门禁结果

| 门禁 | 结果 | 覆盖 | fallback / 降级 | 延迟 | 估算成本 |
| --- | --- | --- | --- | --- | --- |
| 真实依赖门禁 | PASS | 30/30 checks，3/3 实时用例 | 0 / 0 | 最大 18,369.301 ms | USD 0.00543946 |
| 实时质量门禁 | PASS | 34/34 cases，deterministic 34/34，judge 34/34 | 0 / 0 | P95 21,413.888 ms | USD 0.04119053 |

两次最终门禁运行的估算生成成本合计为 **USD 0.04662999**。该数字只包含最终两次门禁报告中的生成成本，不包含排障期间的定点探针和复测调用。

## 真实依赖、检索与生成证据

- Neo4j 实际读取到 323 个 Recipe 节点。
- Milvus 发布别名 `cooking_knowledge__active` 实际读取到 1,543 行向量数据。
- Serving readiness、artifact readiness、检索引擎初始化和系统 readiness 全部为 true。
- 向量菜谱查询：4 条证据，2,913 tokens，18,369.301 ms，USD 0.001297。
- 图关系推理：4 条证据，5,263 tokens，14,386.254 ms，USD 0.002147。
- 组合约束推荐：4 条证据，4,745 tokens，15,235.377 ms，USD 0.001995。
- 三条真实依赖用例均实际使用生成模型，且策略、来源、证据数、token、成本和延迟检查全部通过。
- API 运行时诊断确认模型为 `qwen3.7-plus`、`qwen3-vl-embedding` 和 `qwen3-vl-rerank`。

## 实时检索与质量指标

| 指标 | 实测 | 门槛 | 结果 |
| --- | ---: | ---: | --- |
| Case pass rate | 1.000000 | >= 0.85 | PASS |
| Deterministic pass rate | 1.000000 | >= 0.85 | PASS |
| Judge pass rate | 1.000000 | >= 0.85 | PASS |
| Recall@K | 1.000000 | >= 0.70 | PASS |
| MRR | 0.913043 | >= 0.60 | PASS |
| nDCG@K | 0.935814 | >= 0.70 | PASS |
| Fallback rate | 0.000000 | <= 0.00 | PASS |
| Retrieval degradation rate | 0.000000 | <= 0.00 | PASS |
| P95 latency | 21,413.888 ms | <= 60,000 ms | PASS |
| Estimated cost | USD 0.04119053 | <= USD 2.00 | PASS |

Judge 平均分：faithfulness 0.994118、answer relevance 0.998529、safety 1.000000、completeness 0.989706。

响应模式覆盖：23 条 grounded answer、7 条 no-evidence、2 条 clarification、2 条 constraint conflict，全部通过。高风险切片中的 prompt injection、knowledge pollution、no-evidence inducement、cross-language、typo、long-query 和 constraint-heavy 也全部为 100% 通过。

## Fallback、超时和成本控制

- combined 分支使用隔离的子 RequestControl，单分支超时不再取消父请求。
- combined 默认分支预算从 5 秒校准到 20 秒；复杂图查询不再因过紧预算产生 500 或 fallback。
- 图检索正常 supplement 不再误记为 fallback；真正的空图或分支超时仍记录 fallback。
- 最终两道门禁 fallback 和 retrieval degradation 均为 0。
- 生成证据按项限长，复杂 compose 同时携带有界正文，避免 prompt 成本失控和 judge/生成证据面不一致。
- Judge 使用提供方 JSON-object 模式和严格 schema 校验；有效单例质量结果计入全局/切片阈值，无效 judge 响应或传输故障仍立即阻断发布。

成本按 `qwen3.7-plus` 中国区公开价格人民币 2/8 元每百万输入/输出 token，并按 1 USD = 6.8036 CNY 换算为 USD 0.29396202/1.17584808。参考：[阿里云模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)、[中国银行外汇牌价](https://www.boc.cn/sourcedb/whpj/)。

## 人工复核

人工逐条复核了 `manual_review_sample.jsonl` 中的 **34/34** 条样本，结论为 **PASS**。

复核项包括：

- 主答案与首要检索证据是否一致，菜名、食材、步骤、时间和关系是否有依据；
- 中英法西和拼写容错是否按用户语言/意图回答；
- 无证据、提示注入、知识污染和虚构历史场景是否拒绝编造；
- 澄清场景是否只输出必要问句；冲突场景是否指出不可同时满足的条件；
- 是否出现危险烹饪建议、秘密泄露、API key、Authorization header 或客户数据。

人工复核未发现阻断问题。少量次要候选证据与主问题相关度较低，但首要命中、最终回答、Recall/MRR/nDCG 和 judge 均通过，未影响放行。

## 最终工程验证

- `python -m pytest -q`：1,209 tests + 172 subtests 通过。
- `python scripts/release_gate.py`：69/69 通过；route semantics 24/24、answer pipeline 3/3、real route 3/3、generation plans 3/3、generation prompts 6/6、quality eval 30/30。
- Ruff check：通过。
- Ruff format check：30 个变更 Python 文件均已格式化。
- `git diff --check`：通过。
- Diff 和门禁报告敏感 key 模式扫描：0 命中。

## 产物

- `eval/reports/integration_gate/report.json`
- `eval/reports/integration_gate/summary.md`
- `eval/reports/live_quality_gate/report.json`
- `eval/reports/live_quality_gate/summary.md`
- `eval/reports/live_quality_gate/manual_review_sample.jsonl`
- `eval/reports/release_gate/report.json`
- `eval/reports/release_gate/summary.md`

## 限制与安全建议

Judge 是独立的模型调用，但本次使用了与 Serving 相同的 DashScope 供应商、模型系列和凭据，因此不构成供应商级独立评审；34/34 人工复核用于补充这一限制。

API key 曾在对话中以明文提供。虽然代码 diff 和报告中均未包含该 key，仍建议在交付后立即轮换该凭据，并更新本地运行环境。
