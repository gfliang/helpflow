# HelpFlow Agentic RAG 升级验收清单（Checklist）

## 基础设施与数据

- [x] `alembic upgrade head` 成功，`20261028_0007`、`20261028_0008` 生效。
- [x] 所有 `knowledge_chunks.embedding` 为 512 维且非空（实测 47 条全部 512 维）。
- [x] `make seed` 成功，写入 3 客户、5 订单、2 条 Agent 轨迹；重复执行不重复插入。
- [x] 已发布文档缺少切片时，`seed` 自动触发重建。

## 检索与生成

- [x] 混合检索保留 0.65 向量 + 0.35 词法，候选池可配置，低置信度拒答。
- [x] `HelpFlowRetriever` 封装为 LangChain `BaseRetriever`，MultiQuery 为可选且异常回退。
- [x] 生成链使用 LCEL，流式输出、引用与拒答文案不回退。
- [x] `chat_confidence_threshold=0.4` 与 BGE 得分区间匹配，相关问句可作答。

## Agent 与 HITL

- [x] 只有退款/订单/工单/账单意图进入 Agent，其余走快速 RAG。
- [x] 退款计划强制先资格检查，再提交退款；资格不合格不产生审批。
- [x] `interrupt()` 暂停产生 `AgentApproval(pending)`，会话收到临时说明。
- [x] `approve` 后订单置 `refunded`、run `completed`、写入会话消息与审计日志。
- [x] `reject` 后订单状态不变、run `rejected`、给访客拒绝说明。
- [x] viewer 审批返回 403；admin/agent 可审批。
- [x] PostgresSaver 不可用自动回退 MemorySaver，不阻塞主流程。
- [x] 工具步骤事件写入 `AgentEvent`，`seq` 连续。

## 评测

- [x] `backend/evals/golden_qa.jsonl` 42 条（34 可答 + 8 应拒答）。
- [x] `run_evaluation` 写入 `EvalRun` / `EvalCase`，指标含 hit_rate、citation_accuracy、refusal_accuracy、faithfulness、pass_rate、avg_latency_ms。
- [x] `make eval` 退出码 0，pass_rate 88.1% ≥ 0.8。
- [x] `pass_rate < 0.8` 时 CLI 非 0 退出，`--no-gate` 可关闭。
- [x] `/evals/runs`、`/evals/runs/{id}`、`/evals/summary` 返回正确。

## 前端

- [x] `ConversationDetail` 携带 `agent_runs`，类型定义完整。
- [x] 会话详情展示 Agent 时间线与审批卡片，viewer 只读。
- [x] 审批通过/拒绝后刷新会话与列表，并提示结果。
- [x] 质量日志新增“质量评测”tab，展示最新指标、历史趋势与用例表。
- [x] 登录测试账号、注册页、知识库上传、会话回复/备注/建单均保持可用。
- [x] `npm run build` 通过，无类型错误。
- [x] 页面与文案不出现“演示/demo”。

## 质量门禁

- [x] `uv run ruff check app tests evals` 通过。
- [x] `uv run pytest` 全绿（28 passed），且不访问真实模型/网络。
- [x] `make seed` / `make eval` 在最终代码上重跑通过。
- [x] 浏览器全链路：价格问答流式引用 → 退款工具时间线 → 后台审批 → 退款完成消息 → 评测 tab 指标可见。
